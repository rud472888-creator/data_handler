import argparse

import uvicorn

from orchestrator.dit_app.server import create_app


parser = argparse.ArgumentParser(description="Data Handler DIT workspace")
parser.add_argument("--port", type=int, default=8751)
args = parser.parse_args()
uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
