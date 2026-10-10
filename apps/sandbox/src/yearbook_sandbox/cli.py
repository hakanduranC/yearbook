"""`yearbook-sandbox serve --port 8092`."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from yearbook_sandbox.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yearbook-sandbox")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8092)
    serve.add_argument("--no-selfcheck", action="store_true", help="skip the start-up probe run")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    if args.command == "serve":
        app = create_app(selfcheck=not args.no_selfcheck)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
