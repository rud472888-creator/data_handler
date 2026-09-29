from __future__ import annotations

import argparse
import json
import os


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='Data Handler local agent')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--model-path', required=True)
    init.add_argument('--allowed-root', action='append', default=None)
    sub.add_parser('serve')
    sub.add_parser('inference')
    sub.add_parser('status')
    sub.add_parser('pairing')
    say = sub.add_parser('request')
    say.add_argument('text')
    args = parser.parse_args()
    from orchestrator.agent.config import initialize, load_config
    if args.command == 'init':
        initialize(args.model_path, args.allowed_root or ['/Volumes'])
        print('Initialized local configuration (secrets not printed).')
    elif args.command in {'serve', 'inference'}:
        import uvicorn
        port = int(load_config().get('api_port', 8766)) if args.command == 'serve' else 8767
        if not 1024 <= port <= 65535:
            raise ValueError('Invalid local agent port')
        uvicorn.run('orchestrator.agent.' + ('api' if args.command == 'serve' else 'inference') + ':create_app',
                    factory=True, host='127.0.0.1', port=port,
                    access_log=False)
    elif args.command == 'pairing':
        config = load_config()
        print('Already paired' if config.get('allowed_user_id') else '/start ' + config['pairing_code'])
    else:
        import httpx
        config = load_config()
        headers = {'Authorization': 'Bearer ' + config['api_token']}
        with httpx.Client(trust_env=False, timeout=15) as client:
            result = (client.get('http://127.0.0.1:8766/health', headers=headers) if args.command == 'status'
                      else client.post('http://127.0.0.1:8766/messages', headers=headers, json={'text': args.text}))
            result.raise_for_status()
            print(json.dumps(result.json(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
