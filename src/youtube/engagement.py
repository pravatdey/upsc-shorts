"""
Post-upload engagement: a first comment and optional playlist placement.

Comments on your own Short reliably seed discussion, and discussion is one of
the signals the Shorts feed responds to. The API cannot pin a comment, so the
text is written to work as the top comment whether or not it gets pinned.
"""

from typing import Optional

from googleapiclient.errors import HttpError

from .auth import YouTubeAuth
from src.content.models import ShortScript
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EngagementPoster:
    def __init__(self, auth: YouTubeAuth):
        self.auth = auth

    def post_first_comment(self, video_id: str, script: ShortScript,
                           template: str = None) -> Optional[str]:
        youtube = self.auth.get_service()
        if not youtube:
            return None

        text = self._build_text(script, template)
        if not text:
            return None

        try:
            response = youtube.commentThreads().insert(
                part="snippet",
                body={"snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text[:9000]}},
                }},
            ).execute()
            comment_id = response.get("id", "")
            logger.info(f"Posted first comment on {video_id}")
            return comment_id
        except HttpError as e:
            logger.warning(f"Could not post comment: {e}")
            return None

    @staticmethod
    def _build_text(script: ShortScript, template: str = None) -> str:
        if template:
            try:
                return template.format(
                    question=script.engagement_question,
                    exam_note=script.exam_note,
                    topic=script.topic.title,
                ).strip()
            except KeyError as e:
                logger.warning(f"Comment template has unknown placeholder {e}")

        parts = []
        if script.engagement_question:
            parts.append(script.engagement_question)
        if script.exam_note:
            parts.append(script.exam_note)
        return "\n\n".join(parts)


class PlaylistManager:
    def __init__(self, auth: YouTubeAuth):
        self.auth = auth

    def add_video(self, playlist_id: str, video_id: str) -> bool:
        if not playlist_id:
            return False

        youtube = self.auth.get_service()
        if not youtube:
            return False

        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={"snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }},
            ).execute()
            logger.info(f"Added {video_id} to playlist {playlist_id}")
            return True
        except HttpError as e:
            logger.warning(f"Could not add to playlist: {e}")
            return False
