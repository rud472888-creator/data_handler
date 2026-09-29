from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS inbox (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', result TEXT, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, principal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', run_id TEXT UNIQUE, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    next_try REAL NOT NULL DEFAULT 0, message_id INTEGER);
                CREATE TABLE IF NOT EXISTS subscriptions (
                    run_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, project_id TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    request_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    text TEXT NOT NULL, created REAL NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(self, key: str, payload: dict) -> None:
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO inbox(id,payload,updated) VALUES(?,?,?)',
                       (key, json.dumps(payload), time.time()))

    def out(self, key: str, chat_id: int, payload: dict) -> None:
        text = payload.get('text', '')
        if len(text) > 1800:
            chunks = [text[i:i + 1800] for i in range(0, len(text), 1800)]
            for i, chunk in enumerate(chunks):
                part = {**payload, 'text': chunk}
                if i != len(chunks) - 1:
                    part.pop('reply_markup', None)
                self.out(key + f':part:{i}', chat_id, part)
            return
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO outbox(id,chat_id,payload) VALUES(?,?,?)',
                       (key, chat_id, json.dumps(payload, ensure_ascii=False)))

    def meta(self, key: str, default: str = '') -> str:
        with self.connect() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, value))

    def create_conversation(self, key: str, project_id: str | None) -> dict:
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',
                       (key, '새 대화', project_id, now, now))
        return {'id': key, 'title': '새 대화', 'project_id': project_id}

    def conversations(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM conversations ORDER BY updated DESC LIMIT 100')]

    def conversation(self, key: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=?', (key,)).fetchone()
            if not row:
                raise KeyError(key)
            result = dict(row)
            turns = db.execute('''SELECT t.request_id,t.text,t.created,i.status,i.result
                FROM conversation_turns t JOIN inbox i ON i.id=t.request_id
                WHERE t.conversation_id=? ORDER BY t.created,t.rowid''', (key,)).fetchall()
        result['turns'] = [{**dict(r), 'result': json.loads(r['result']) if r['result'] else None} for r in turns]
        return result

    def enqueue_turn(self, conversation_id: str, request_id: str, text: str) -> dict:
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            conversation = db.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
            if not conversation:
                raise KeyError(conversation_id)
            previous = db.execute('SELECT * FROM conversation_turns WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['conversation_id'] != conversation_id or previous['text'] != text:
                    raise ValueError('동일한 요청 ID의 내용이 변경되었습니다.')
                return {'id': request_id}
            busy = db.execute('''SELECT 1 FROM conversation_turns t JOIN inbox i ON t.request_id=i.id
                WHERE t.conversation_id=? AND i.status!='done' LIMIT 1''', (conversation_id,)).fetchone()
            if busy:
                raise ValueError('이 대화의 앞선 요청을 처리하고 있습니다.')
            payload = {'text': text, 'principal': 'desktop:' + conversation_id,
                       'conversation_id': conversation_id, 'project_id': conversation['project_id']}
            db.execute('INSERT INTO inbox(id,payload,updated) VALUES(?,?,?)', (request_id, json.dumps(payload), now))
            db.execute('INSERT INTO conversation_turns VALUES(?,?,?,?)', (request_id, conversation_id, text, now))
            db.execute('UPDATE conversations SET updated=?,title=CASE WHEN title=? THEN ? ELSE title END WHERE id=?',
                       (now, '새 대화', text[:48], conversation_id))
        return {'id': request_id}
