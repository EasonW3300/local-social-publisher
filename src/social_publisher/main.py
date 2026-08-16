from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

import uvicorn

from .api import create_app
from .runtime import PublisherRuntime


def default_data_dir() -> Path:
    override = os.environ.get("LOCAL_SOCIAL_PUBLISHER_DATA")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local-social-publisher"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Local Social Publisher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the application may only listen on loopback")

    runtime = PublisherRuntime(default_data_dir())
    runtime.start()
    app = create_app(
        runtime.data_dir,
        dispatch_jobs=runtime.dispatch,
        settings_service=runtime.settings,
    )
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
