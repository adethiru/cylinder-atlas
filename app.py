#!/usr/bin/env python3
"""Cylinder Atlas - start the app.

    python3 app.py            # opens http://127.0.0.1:8765
    python3 app.py --reset    # rebuild the database from data/targets_seed.json
    python3 app.py --no-browser --port 8800

Standard library only: no pip install needed (Python 3.9+).
"""
import argparse
import sys
import threading
import webbrowser

if sys.version_info < (3, 9):
    sys.exit("Cylinder Atlas needs Python 3.9 or newer. Check with: python3 --version")

from atlas import config, db, server  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Cylinder Atlas")
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--reset", action="store_true", help="rebuild the database from the seed file")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    db.init(reset=a.reset)
    url = f"http://127.0.0.1:{a.port}"
    print("\n  Cylinder Atlas - industrial gas roll-up desk")
    print(f"  Open {url}   (Ctrl+C to stop)")
    print(f"  Model: {config.MODEL} via {config.PROVIDER}   |   key file: {config.ENV_FILE_USED or 'NOT FOUND'}")
    if config.PROVIDER == "none" and not config.MOCK:
        print("  WARNING: no PORTKEY_API_KEY / OPENAI_API_KEY found in ./.env or ../.env - the map works, agents will not.")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve(a.port)
    except OSError as e:
        sys.exit(f"Could not start on port {a.port} ({e}). Try: python3 app.py --port 8800")
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
