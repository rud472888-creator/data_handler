from __future__ import annotations

import json
import logging
import secrets
import time
import hashlib
from pathlib import Path

import httpx

from orchestrator.agent.config import config_path, private_json
from orchestrator.agent.service import AgentService

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token: str):
        self._base = 'https://api.telegram.org/bot' + token

    def call(self, method: str, payload: dict, *, document: Path | None = None):
        # Never include request URLs/exceptions in logs: Telegram URLs contain the token.
        try:
            with httpx.Client(timeout=40, trust_env=False) as client:
                if document:
                    with document.open('rb') as file:
                        response = client.post(self._base + '/' + method, data=payload,
                                               files={'document': (document.name, file)})
                else:
                    response = client.post(self._base + '/' + method, json=payload)
                data = response.json()
                if not data.get('ok'):
                    raise RuntimeError('Telegram API rejected request')
                return data['result']
        except Exception:
            raise RuntimeError('Telegram unavailable; delivery remains queued') from None


def accept_update(service: AgentService, update: dict) -> bool:
    config = service.config
    callback = update.get('callback_query')
    message = callback.get('message', {}) if callback else update.get('message', {})
    sender = callback.get('from', {}) if callback else message.get('from', {})
    chat = message.get('chat', {})
    if chat.get('type') != 'private' or sender.get('is_bot'):
        return False
    user_id, chat_id = sender.get('id'), chat.get('id')
    if not isinstance(user_id, int) or chat_id != user_id:
        return False
    text = message.get('text', '') if not callback else ''
    if not config.get('allowed_user_id'):
        expected = '/start ' + config['pairing_code']
        if not secrets.compare_digest(text, expected):
            return False
        config['allowed_user_id'] = user_id
        config['allowed_chat_id'] = chat_id
        config['pairing_code'] = ''
        private_json(config_path(), config)
        service.store.out('paired', chat_id, {'text': 'Data Handler 연결 완료. 이 계정만 작업을 요청할 수 있습니다. /help'})
        return True
    if user_id != config['allowed_user_id'] or chat_id != config['allowed_chat_id']:
        return False
    if callback:
        data = callback.get('data', '')
        if not data.startswith('approve:'):
            return False
        text = '/approve ' + data.removeprefix('approve:')
    if not isinstance(text, str) or not text or len(text) > 6000:
        return False
    service.store.enqueue('tg:' + str(update['update_id']),
                          {'text': text, 'principal': 'telegram:' + str(user_id), 'chat_id': chat_id})
    return True


def receiver(service: AgentService, stopped):
    while not stopped.is_set():
        path = Path(service.config['telegram_token_file'])
        if not path.is_file():
            stopped.wait(5)
            continue
        transport = Telegram(path.read_text().strip())
        try:
            offset = int(service.store.meta('telegram_offset', '0'))
            updates = transport.call('getUpdates', {'offset': offset, 'timeout': 20,
                                                    'allowed_updates': ['message', 'callback_query']})
            for update in updates:
                accepted = accept_update(service, update)
                service.store.set_meta('telegram_offset', str(update['update_id'] + 1))
                callback = update.get('callback_query')
                if accepted and callback:
                    transport.call('answerCallbackQuery', {'callback_query_id': callback['id'],
                                                          'text': '로컬 작업 큐에 접수했습니다.'})
            service.store.set_meta('telegram_last_connected', str(time.time()))
        except Exception:
            stopped.wait(10)


def deliver_once(service: AgentService, transport: Telegram):
    with service.store.connect() as db:
        rows = db.execute("SELECT * FROM outbox WHERE status='pending' AND next_try<=? ORDER BY rowid LIMIT 10",
                          (time.time(),)).fetchall()
    for row in rows:
        payload = json.loads(row['payload'])
        try:
            document = Path(payload['document']) if payload.get('document') else None
            if document and (not document.is_file() or document.stat().st_size > 49 * 1024**2):
                raise RuntimeError('Attachment unavailable or exceeds configured upload budget')
            if document and (document.is_symlink() or not document.resolve().is_relative_to((service.root / 'runs').resolve())
                             or hashlib.sha256(document.read_bytes()).hexdigest() != payload.get('sha256')):
                raise RuntimeError('Attachment identity changed')
            body = {k: v for k, v in payload.items() if k not in {'document', 'sha256'}}
            body['chat_id'] = row['chat_id']
            result = transport.call('sendDocument' if document else 'sendMessage', body, document=document)
            with service.store.connect() as db:
                db.execute("UPDATE outbox SET status='sent',message_id=? WHERE id=?", (result['message_id'], row['id']))
        except Exception:
            with service.store.connect() as db:
                db.execute('UPDATE outbox SET attempts=attempts+1,next_try=? WHERE id=?',
                           (time.time() + min(300, 2**min(row['attempts'] + 2, 8)), row['id']))


def sender(service: AgentService, stopped):
    while not stopped.is_set():
        try:
            service.collect_reports()
            path = Path(service.config['telegram_token_file'])
            if path.is_file():
                deliver_once(service, Telegram(path.read_text().strip()))
        except Exception:
            log.warning('Report collection/delivery deferred; local tasks are unaffected')
        stopped.wait(5)


def command_worker(service: AgentService, stopped):
    # Only one service process owns this worker. Restart interrupted requests; execution
    # itself is separately claimed in plans and will never be repeated on this replay.
    with service.store.connect() as db:
        db.execute("UPDATE inbox SET status='pending' WHERE status='processing'")
    while not stopped.is_set():
        with service.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM inbox WHERE status='pending' ORDER BY updated LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE inbox SET status='processing',updated=? WHERE id=?", (time.time(), row['id']))
        if not row:
            stopped.wait(1)
            continue
        request = json.loads(row['payload'])
        approval = None
        try:
            history = []
            if request.get('conversation_id'):
                turns = service.store.conversation(request['conversation_id'])['turns']
                for turn in [t for t in turns if t['request_id'] != row['id']][-4:]:
                    history.append({'role': 'user', 'text': turn['text'][:1500]})
                    if turn['result']:
                        history.append({'role': 'assistant', 'text': str(turn['result'].get('text', ''))[:1500]})
            elif request.get('chat_id') is not None:
                with service.store.connect() as db:
                    previous = db.execute("SELECT payload,result FROM inbox WHERE status='done' AND rowid < (SELECT rowid FROM inbox WHERE id=?) AND json_extract(payload,'$.principal')=? ORDER BY rowid DESC LIMIT 4",
                                          (row['id'], request['principal'])).fetchall()
                for turn in reversed(previous):
                    history.append({'role': 'user', 'text': json.loads(turn['payload'])['text'][:1500]})
                    history.append({'role': 'assistant', 'text': str(json.loads(turn['result'] or '{}').get('text', ''))[:1500]})
            result = service.interpret(request['text'], request['principal'], history=history,
                                       project_id=request.get('project_id'))
            if 'approve' in result:
                approval = result['approve']
                destination = request.get('chat_id')
                if request.get('conversation_id'):
                    destination = service.config.get('allowed_chat_id')
                execution = service.execute(result['approve'], request['principal'], destination)
                result = {'text': f"작업 접수 결과: {execution['status']}\n작업 ID: {execution['run_id']}\n"
                                  '인터넷 연결과 관계없이 로컬에서 진행하고 종료 후 보고합니다.', **execution}
        except Exception as exc:
            # Avoid transporting exception strings from networking libraries containing URLs.
            detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            result = {'text': '작업 확인이 필요합니다: ' + detail[:1000], 'error': True}
            if approval:
                with service.store.connect() as db:
                    plan = db.execute('SELECT run_id,status FROM plans WHERE id=? AND principal=?',
                                      (approval, request['principal'])).fetchone()
                if plan and plan['run_id']:
                    result.update(run_id=plan['run_id'], status=plan['status'])
                    result['text'] += '\n작업 ID: ' + plan['run_id']
        if request.get('chat_id') is not None:
            service.store.out('reply:' + row['id'], request['chat_id'],
                              {k: v for k, v in result.items() if k in {'text', 'reply_markup'}})
        with service.store.connect() as db:
            db.execute("UPDATE inbox SET status='done',result=?,updated=? WHERE id=?",
                       (json.dumps(result, ensure_ascii=False), time.time(), row['id']))
