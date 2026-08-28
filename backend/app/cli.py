import argparse

import uvicorn

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local coding agent with native tool calling")
    parser.add_argument("workspace", help="Existing directory authorized as the workspace")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        app = create_app(Settings.from_env(args.workspace, args.port))
    except (ValueError, OSError):
        parser.error("Invalid workspace or configuration; check the directory, port and MAX_STEPS")
    # Deliberately no host/workers option in the single-user foundation.
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
