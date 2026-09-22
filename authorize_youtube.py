"""
One-time YouTube authorization.

Run this on your own machine (not in CI):

    python authorize_youtube.py

It opens a browser, asks you to sign in to the channel, and writes
config/youtube_token.json. Paste the contents of that file into the
YOUTUBE_TOKEN GitHub secret so the daily workflow can upload without a browser.

Before running, download the OAuth client from Google Cloud Console
(APIs & Services -> Credentials -> OAuth client ID -> Desktop app) and save it
as config/client_secrets.json.
"""

import json
import sys
from pathlib import Path

from src.utils.logger import setup_logger
from src.youtube.auth import YouTubeAuth

SECRETS = Path("config/client_secrets.json")
TOKEN = Path("config/youtube_token.json")


def main() -> int:
    setup_logger()

    if not SECRETS.exists():
        print(f"Missing {SECRETS}")
        print()
        print("Get it from Google Cloud Console:")
        print("  1. Create a project and enable the YouTube Data API v3")
        print("  2. APIs & Services -> Credentials -> Create OAuth client ID")
        print("  3. Application type: Desktop app")
        print(f"  4. Download the JSON and save it as {SECRETS}")
        return 1

    auth = YouTubeAuth(str(SECRETS), str(TOKEN))
    if not auth.authenticate():
        print("Authorization failed. See the log above for details.")
        return 1

    youtube = auth.get_service()
    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items", [])
    channel = items[0]["snippet"]["title"] if items else "unknown"

    print()
    print(f"Authorized channel: {channel}")
    print(f"Token written to:   {TOKEN}")
    print()
    print("Now add it as a GitHub secret named YOUTUBE_TOKEN:")
    print("  Repo -> Settings -> Secrets and variables -> Actions -> New secret")
    print("  Paste the entire contents of the file below as the value.")
    print()
    print("-" * 68)
    print(json.dumps(json.loads(TOKEN.read_text(encoding="utf-8"))))
    print("-" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
