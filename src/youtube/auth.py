"""
YouTube OAuth2.

In CI there is no browser, so credentials must arrive fully formed through the
YOUTUBE_TOKEN_JSON secret. Locally, `python authorize_youtube.py` runs the
consent flow once and writes config/youtube_token.json.
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.utils.logger import get_logger

logger = get_logger(__name__)


class YouTubeAuth:
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ]

    def __init__(self, client_secrets_file: str = "config/client_secrets.json",
                 token_file: str = "config/youtube_token.json"):
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        self.credentials: Optional[Credentials] = None
        self.youtube = None

    def authenticate(self) -> bool:
        try:
            self.credentials = self._load_credentials()

            if self.credentials and self.credentials.valid:
                return self._build_service()

            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                try:
                    self.credentials.refresh(Request())
                    self._save_credentials()
                    return self._build_service()
                except Exception as e:
                    logger.error(f"Token refresh failed: {e}")

            return self._interactive_flow()

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def get_service(self):
        if not self.youtube:
            self.authenticate()
        return self.youtube

    # ---- credential loading ----

    def _load_credentials(self) -> Optional[Credentials]:
        env_token = os.environ.get("YOUTUBE_TOKEN_JSON")
        if env_token:
            data = _parse_token(env_token)
            if data:
                credentials = _credentials_from(data)
                if credentials:
                    logger.info("Loaded YouTube credentials from environment")
                    return credentials
            logger.error("YOUTUBE_TOKEN_JSON is set but could not be parsed")

        token_path = Path(self.token_file)
        if token_path.exists():
            try:
                with open(token_path, "r", encoding="utf-8-sig") as f:
                    data = _parse_token(f.read())
                if data:
                    return _credentials_from(data)
            except Exception as e:
                logger.error(f"Could not read {self.token_file}: {e}")

        return None

    def _save_credentials(self) -> None:
        path = Path(self.token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "token": self.credentials.token,
                "refresh_token": self.credentials.refresh_token,
                "token_uri": self.credentials.token_uri,
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "scopes": self.credentials.scopes,
            }, f, indent=2)

    def _interactive_flow(self) -> bool:
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            logger.error(
                "No valid YouTube token in CI. Set the YOUTUBE_TOKEN secret from "
                "the config/youtube_token.json produced by authorize_youtube.py"
            )
            return False

        secrets_path = Path(self.client_secrets_file)
        if not secrets_path.exists():
            logger.error(f"Client secrets not found: {self.client_secrets_file}")
            return False

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_path), scopes=self.SCOPES
            )
            self.credentials = flow.run_local_server(
                port=0, prompt="consent",
                success_message="Authorized. You can close this window.",
            )
            self._save_credentials()
            return self._build_service()
        except Exception as e:
            logger.error(f"OAuth flow failed: {e}")
            return False

    def _build_service(self) -> bool:
        try:
            self.youtube = build("youtube", "v3", credentials=self.credentials,
                                 cache_discovery=False)
            return True
        except Exception as e:
            logger.error(f"Could not build YouTube service: {e}")
            return False


def _parse_token(content: str) -> Optional[dict]:
    """Accept raw JSON, JSON with a BOM, or base64-encoded JSON."""
    content = content.strip()
    for attempt in (content, content.lstrip("﻿")):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(base64.b64decode(content).decode("utf-8"))
    except Exception:
        return None


def _credentials_from(data: dict) -> Optional[Credentials]:
    required = ["token", "refresh_token", "token_uri", "client_id", "client_secret"]
    missing = [field for field in required if not data.get(field)]
    if missing:
        logger.error(f"Token is missing required fields: {', '.join(missing)}")
        return None
    return Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data.get("scopes"),
    )
