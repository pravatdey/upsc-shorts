"""
YouTube uploader with resumable upload and retry.

YouTube classifies a video as a Short automatically from its shape and length
(vertical, 60 seconds or less) — there is no API flag for it. What this module
controls is everything else: metadata, privacy, and the thumbnail.
"""

import http.client
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httplib2
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .auth import YouTubeAuth
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 8
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error, IOError, http.client.NotConnected,
    http.client.IncompleteRead, http.client.ImproperConnectionState,
    http.client.CannotSendRequest, http.client.CannotSendHeader,
    http.client.ResponseNotReady, http.client.BadStatusLine,
)
RETRIABLE_STATUS = {500, 502, 503, 504}


@dataclass
class UploadResult:
    success: bool
    video_id: str = ""
    video_url: str = ""
    error: Optional[str] = None


class YouTubeUploader:
    def __init__(self, auth: YouTubeAuth = None):
        self.auth = auth or YouTubeAuth()

    def upload(self, video_path: str, title: str, description: str,
               tags: List[str] = None, category_id: str = "27",
               privacy_status: str = "public", thumbnail_path: str = None,
               made_for_kids: bool = False,
               language: str = "hi") -> UploadResult:

        if not Path(video_path).exists():
            return UploadResult(False, error=f"Video not found: {video_path}")

        youtube = self.auth.get_service()
        if not youtube:
            return UploadResult(False, error="YouTube authentication failed")

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": _fit_tags(tags or []),
                "categoryId": category_id,
                "defaultLanguage": language,
                "defaultAudioLanguage": language,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids,
                "embeddable": True,
                "publicStatsViewable": True,
            },
        }

        try:
            media = MediaFileUpload(
                video_path, chunksize=4 * 1024 * 1024, resumable=True,
                mimetype="video/*",
            )
            request = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )

            logger.info(f"Uploading: {title}")
            response = self._resumable_upload(request)
            if not response:
                return UploadResult(False, error="Upload failed after retries")

            video_id = response.get("id", "")
            video_url = f"https://www.youtube.com/shorts/{video_id}"
            logger.info(f"Uploaded: {video_url}")

            if thumbnail_path and Path(thumbnail_path).exists():
                self._set_thumbnail(youtube, video_id, thumbnail_path)

            return UploadResult(True, video_id, video_url)

        except HttpError as e:
            detail = e.content.decode(errors="replace") if e.content else str(e)
            logger.error(f"Upload failed ({e.resp.status}): {detail}")
            return UploadResult(False, error=f"HTTP {e.resp.status}: {detail}")
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return UploadResult(False, error=str(e))

    @staticmethod
    def _resumable_upload(request) -> Optional[Dict]:
        response = None
        retry = 0

        while response is None:
            error = None
            try:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS:
                    error = f"retriable HTTP {e.resp.status}"
                else:
                    raise
            except RETRIABLE_EXCEPTIONS as e:
                error = f"retriable error: {e}"

            if error:
                retry += 1
                if retry > MAX_RETRIES:
                    logger.error(f"Giving up after {MAX_RETRIES} retries ({error})")
                    return None
                wait = 2 ** retry
                logger.warning(f"{error}; retrying in {wait}s")
                time.sleep(wait)

        return response

    @staticmethod
    def _set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            logger.info("Custom thumbnail set")
        except HttpError as e:
            # Custom thumbnails need a verified channel; not having one is not
            # a reason to fail an otherwise successful upload.
            logger.warning(f"Thumbnail not set (channel may need verification): {e}")


def _fit_tags(tags: List[str]) -> List[str]:
    """
    YouTube caps the tags field at 500 characters in total, not 500 tags.

    Exceeding it rejects the whole request, so trim to fit rather than letting
    the upload fail on metadata.
    """
    selected: List[str] = []
    budget = 480  # leave headroom for the separators YouTube adds
    used = 0
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        cost = len(tag) + 1
        if used + cost > budget:
            break
        selected.append(tag)
        used += cost
    return selected
