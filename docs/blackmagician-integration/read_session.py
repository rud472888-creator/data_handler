"""Read ONE initial NDJSON entries snapshot; never join, edit, or control a camera.
Usage: python read_session.py /secure/path/test-web-session.json
Requires httpx. Input is an existing, approved join-response JSON (mode 0600).
Only a redacted summary is printed. fetch_entries returns data in memory.
"""
import asyncio
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urljoin, urlsplit
import httpx

BASE = 'https://blackmagician-web.vercel.app'

async def fetch_entries(session):
    url = urljoin(BASE, session['eventsUrl'])
    target = urlsplit(url)
    if target.scheme != 'https' or target.netloc != urlsplit(BASE).netloc or target.username or target.password:
        raise ValueError('unapproved_events_origin')
    # Do not forward credentials to redirects or an unapproved cross-cloud origin.
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        async with client.stream('GET', url, headers={'Authorization': 'Bearer ' + session['token']}) as response:
            if response.status_code != 200:
                raise ValueError('http_' + str(response.status_code))
            if response.headers.get('content-type', '').split(';')[0] != 'application/x-ndjson':
                raise ValueError('unexpected_content_type')
            buffer = b''
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > 32 * 1024 * 1024:
                    raise ValueError('response_size_limit')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get('type') == 'error':
                        raise ValueError('stream_error')
                    if event.get('type') == 'entries':
                        if not isinstance(event.get('data'), list) or not all(isinstance(x, dict) for x in event['data']):
                            raise ValueError('invalid_entries')
                        return {'projectId': session['projectId'], 'sessionId': session['sessionId'],
                                'serverTime': event.get('serverTime'), 'entries': event['data']}
            raise ValueError('ended_before_entries')

async def main():
    path = Path(sys.argv[1])
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('credential_file_must_be_private')
    session = json.loads(path.read_text())
    result = await asyncio.wait_for(fetch_entries(session), timeout=25)
    rows = result['entries']
    print(json.dumps({'initial_entries_received': True, 'count': len(rows),
                      'entry_fields': sorted({k for row in rows for k in row}),
                      'identifiers_and_values': 'redacted'}, ensure_ascii=False))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except ValueError as exc:
        # Only explicit diagnostic codes; never print server payloads or URLs.
        allowed = {'unapproved_events_origin', 'unexpected_content_type', 'response_size_limit',
                   'stream_error', 'invalid_entries', 'ended_before_entries', 'credential_file_must_be_private'}
        message = str(exc)
        print(message if message in allowed or (message.startswith('http_') and message[5:].isdigit()) else 'invalid_input_or_payload', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        sys.exit(1)
