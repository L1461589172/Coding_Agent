"""Trusted launcher: wait for the supervisor's go-ahead BEFORE starting user code.

Executed with Python -I, not imported by the application. On Windows the supervisor
assigns this process to a kill-on-close Job before sending the JSON request.
"""

import json
import os
import subprocess
import sys


def main() -> int:
    request = sys.stdin.buffer.readline(128 * 1024)
    if not request:
        return 125
    try:
        args = json.loads(request)
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        code = process.wait()
        if os.name != "nt" and code < 0:
            os.kill(os.getpid(), -code)  # Preserve signal exit status through the launcher.
        return code
    except (OSError, ValueError):
        print("Local command could not be started", file=sys.stderr, flush=True)
        return 127


if __name__ == "__main__":
    sys.exit(main())
