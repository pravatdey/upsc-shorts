"""
Daily UPSC Shorts pipeline.

    python main.py                      generate and upload today's batch
    python main.py --count 1            just one Short
    python main.py --no-upload          build locally, upload nothing
    python main.py --test               upload as private (safe first run)
    python main.py --topic geo-001      force a specific topic
    python main.py --status             show what has been published so far
    python main.py --list-topics        print the topic bank

Each video runs the same seven steps: pick topic -> write script -> narrate ->
compose -> thumbnail -> upload -> record. A failure on one video is contained;
the rest of the batch still runs.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.content.models import ShortScript, Topic
from src.content.script_writer import ScriptWriter
from src.content.topic_bank import TopicBank
from src.llm.client import LLMClient
from src.tts.tts_manager import TTSManager
from src.utils.database import Database
from src.utils.logger import get_logger, setup_logger
from src.utils.progress_store import ProgressStore
from src.video.composer import ShortComposer, fit_audio_duration
from src.video.fonts import FontBook
from src.youtube.auth import YouTubeAuth
from src.youtube.engagement import EngagementPoster, PlaylistManager
from src.youtube.metadata import MetadataGenerator
from src.youtube.uploader import YouTubeUploader


class ShortsPipeline:
    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config: Dict[str, Any] = yaml.safe_load(f)

        setup_logger(log_file="logs/pipeline.log")
        self.logger = get_logger("pipeline")

        self.progress = ProgressStore("progress.json")
        self.db = Database(self.config.get("database", {}).get("path",
                                                              "data/shorts_tracker.db"))
        self.topics = TopicBank(self.config.get("topics", {}).get("file",
                                                                 "config/topics.yaml"))

        script_config = self.config.get("script", {})
        llm_config = self.config.get("llm", {})
        self.writer = ScriptWriter(
            llm=LLMClient(
                provider=llm_config.get("provider", "groq"),
                groq_model=llm_config.get("groq_model", "llama-3.3-70b-versatile"),
                gemini_model=llm_config.get("gemini_model", "gemini-2.5-flash"),
            ),
            language=script_config.get("language", "hindi"),
            target_seconds=script_config.get("target_seconds", 48),
            words_per_second=script_config.get("words_per_second", 2.6),
        )
        self.max_seconds = float(script_config.get("max_seconds", 58))

        self.tts = TTSManager(self.config)

        # One FontBook shared by every renderer — resolving and loading fonts is
        # expensive and the result is identical across videos.
        self.fonts = FontBook()
        self.composer = ShortComposer(self.config, fonts=self.fonts)
        self.metadata = MetadataGenerator()

        self._auth: Optional[YouTubeAuth] = None
        self._uploader: Optional[YouTubeUploader] = None

        self.output = self.config.get("output", {})

    # ---- lazy YouTube clients (never built for --no-upload runs) ----

    @property
    def auth(self) -> YouTubeAuth:
        if self._auth is None:
            self._auth = YouTubeAuth()
        return self._auth

    @property
    def uploader(self) -> YouTubeUploader:
        if self._uploader is None:
            self._uploader = YouTubeUploader(self.auth)
        return self._uploader

    # ---- batch ----

    async def run_batch(self, count: int = None, upload: bool = True,
                        test_mode: bool = False,
                        topic_ids: List[str] = None) -> List[Dict[str, Any]]:
        batch_config = self.config.get("batch", {})
        count = count or batch_config.get("videos_per_run", 3)
        delay = batch_config.get("delay_between_videos_seconds", 30)

        topics = self._select_topics(count, topic_ids)
        if not topics:
            self.logger.error("No topics available to generate")
            return []

        self.logger.info(
            f"Batch of {len(topics)}: " + ", ".join(t.id for t in topics)
        )

        results: List[Dict[str, Any]] = []
        for i, topic in enumerate(topics):
            if i > 0 and delay:
                # Spacing requests keeps the free TTS tier from rate-limiting us,
                # and staggers upload times, which looks more natural on a channel.
                self.logger.info(f"Waiting {delay}s before the next video")
                await asyncio.sleep(delay)

            result = await self._make_one(topic, upload=upload, test_mode=test_mode)
            results.append(result)

            self.progress.set_last_run(datetime.utcnow().isoformat(timespec="seconds"))
            self.progress.save()

        succeeded = sum(1 for r in results if r["success"])
        self.logger.info(f"Batch finished: {succeeded}/{len(results)} succeeded")
        return results

    def _select_topics(self, count: int, topic_ids: List[str] = None) -> List[Topic]:
        if topic_ids:
            picked = []
            for topic_id in topic_ids:
                topic = self.topics.by_id(topic_id)
                if topic:
                    picked.append(topic)
                else:
                    self.logger.error(f"Unknown topic id: {topic_id}")
            return picked

        # Seed the category rotation by day so consecutive days do not always
        # open with the same category.
        seed = int(datetime.utcnow().strftime("%j"))
        return self.topics.pick(count, self.progress.used_topic_ids, seed=seed)

    # ---- one video ----

    async def _make_one(self, topic: Topic, upload: bool,
                        test_mode: bool) -> Dict[str, Any]:
        result: Dict[str, Any] = {"success": False, "topic_id": topic.id,
                                  "title": topic.title}
        serial = self.progress.serial + 1

        # Reserve the topic now so a crash mid-run cannot silently re-pick it.
        self.progress.mark_used(topic.id)
        self.db.create_record(topic.id, serial, topic.title, topic.category)

        try:
            self.logger.info(f"=== {topic.id}: {topic.title} ===")

            # 1. Script
            script = self.writer.write(topic)
            script_path = self._save_script(script, serial)
            self.db.update(topic.id, status="pending", script_path=str(script_path))

            # 2. Narration
            audio_path = str(Path(self.output.get("audio_dir", "output/audio"))
                             / f"short_{serial:04d}.mp3")
            narration = script.narration_text()
            self.logger.info(f"Narrating {len(narration.split())} words")

            tts_result = await self.tts.narrate(narration, audio_path)
            if not tts_result.success:
                raise RuntimeError(f"Narration failed: {tts_result.error}")

            duration, words = fit_audio_duration(
                audio_path, tts_result.words, tts_result.duration, self.max_seconds
            )
            self.logger.info(f"Narration ready: {duration:.1f}s")
            self.db.update(topic.id, audio_path=audio_path, duration=duration)

            # 3. Thumbnail (cover art for search and the channel grid)
            thumb_path = str(Path(self.output.get("thumbnail_dir", "output/thumbnails"))
                             / f"short_{serial:04d}.jpg")
            Path(thumb_path).parent.mkdir(parents=True, exist_ok=True)
            self.composer.cards.render_thumbnail(script).save(thumb_path, quality=92)

            # 4. Video
            video_path = str(Path(self.output.get("video_dir", "output/videos"))
                             / f"short_{serial:04d}.mp4")
            self.composer.compose(script, audio_path, words, duration, video_path)

            self.db.update(topic.id, status="generated", video_path=video_path,
                           thumbnail_path=thumb_path)
            result.update(video_path=video_path, duration=duration,
                          title=script.title)

            if not upload:
                self.logger.info(f"Generated (upload skipped): {video_path}")
                result["success"] = True
                return result

            # 5. Upload
            meta = self.metadata.generate(script, serial)
            privacy = "private" if test_mode else \
                self.config.get("youtube", {}).get("privacy_status", "public")

            upload_result = self.uploader.upload(
                video_path=video_path,
                title=meta["title"],
                description=meta["description"],
                tags=meta["tags"],
                category_id=meta["category_id"],
                privacy_status=privacy,
                thumbnail_path=thumb_path,
                made_for_kids=meta["made_for_kids"],
                language=meta["language"],
            )
            if not upload_result.success:
                raise RuntimeError(f"Upload failed: {upload_result.error}")

            self.db.update(topic.id, status="uploaded",
                           youtube_id=upload_result.video_id,
                           youtube_url=upload_result.video_url)

            serial = self.progress.record_upload(
                topic_id=topic.id, title=meta["title"],
                video_id=upload_result.video_id, url=upload_result.video_url,
                date=datetime.utcnow().strftime("%Y-%m-%d"),
            )

            # 6. Post-upload engagement (never fatal)
            self._post_upload(upload_result.video_id, script)

            result.update(success=True, youtube_url=upload_result.video_url,
                          video_id=upload_result.video_id, title=meta["title"])
            self.logger.info(f"=== DONE {topic.id}: {upload_result.video_url} ===")

        except Exception as e:
            self.logger.error(f"Failed on {topic.id}: {e}", exc_info=True)
            self.db.update(topic.id, status="failed", error=str(e))
            # Hand the topic back so tomorrow's run retries it instead of
            # burning it on a failure.
            self.progress.release(topic.id)
            result["error"] = str(e)

        return result

    def _post_upload(self, video_id: str, script: ShortScript) -> None:
        youtube_config = self.config.get("youtube", {})

        if youtube_config.get("post_first_comment", True):
            try:
                template = self.metadata.config.get("comment", {}).get(
                    "first_comment_template"
                )
                EngagementPoster(self.auth).post_first_comment(
                    video_id, script, template
                )
            except Exception as e:
                self.logger.warning(f"First comment skipped: {e}")

        playlist_id = youtube_config.get("playlist_id")
        if playlist_id:
            try:
                PlaylistManager(self.auth).add_video(playlist_id, video_id)
            except Exception as e:
                self.logger.warning(f"Playlist add skipped: {e}")

    def _save_script(self, script: ShortScript, serial: int) -> Path:
        path = Path(self.output.get("script_dir", "output/scripts")) \
            / f"short_{serial:04d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "topic_id": script.topic.id,
                "topic": script.topic.title,
                "category": script.topic.category,
                "title": script.title,
                "beats": [
                    {"kind": b.kind.value, "headline": b.headline,
                     "narration": b.narration}
                    for b in script.beats
                ],
                "exam_note": script.exam_note,
                "engagement_question": script.engagement_question,
                "keywords": script.keywords,
                "word_count": script.total_words(),
            }, f, indent=2, ensure_ascii=False)
        return path

    # ---- reporting ----

    def print_status(self) -> None:
        stats = self.db.get_progress()
        used = len(self.progress.used_topic_ids)
        print("\n=== UPSC Shorts ===")
        print(f"Topic bank      : {self.topics.total} topics")
        print(f"Used            : {used} ({self.topics.total - used} remaining)")
        print(f"Published       : {self.progress.serial}")
        print(f"DB uploaded     : {stats['uploaded']}  generated: {stats['generated']}"
              f"  failed: {stats['failed']}")
        print(f"Last run        : {self.progress.data.get('last_run') or 'never'}")

        recent = self.progress.data.get("uploads", [])[-5:]
        if recent:
            print("\nRecent uploads:")
            for item in reversed(recent):
                print(f"  {item['date']}  {item['url']}  {item['title'][:60]}")
        print()

    def print_topics(self) -> None:
        used = set(self.progress.used_topic_ids)
        for topic in self.topics.topics:
            mark = "x" if topic.id in used else " "
            print(f"[{mark}] {topic.id:<10} {topic.category:<24} {topic.title}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily UPSC Shorts pipeline")
    parser.add_argument("--count", type=int, help="How many Shorts to make")
    parser.add_argument("--topic", action="append", dest="topics",
                        help="Force a specific topic id (repeatable)")
    parser.add_argument("--no-upload", action="store_true",
                        help="Generate locally without uploading")
    parser.add_argument("--test", action="store_true",
                        help="Upload as private")
    parser.add_argument("--status", action="store_true", help="Show progress")
    parser.add_argument("--list-topics", action="store_true", help="List the topic bank")
    args = parser.parse_args()

    pipeline = ShortsPipeline()

    if args.status:
        pipeline.print_status()
        return 0

    if args.list_topics:
        pipeline.print_topics()
        return 0

    started = time.time()
    results = asyncio.run(pipeline.run_batch(
        count=args.count,
        upload=not args.no_upload,
        test_mode=args.test,
        topic_ids=args.topics,
    ))

    print(f"\n=== Batch complete in {time.time() - started:.0f}s ===")
    for result in results:
        if result["success"]:
            location = result.get("youtube_url") or result.get("video_path")
            print(f"  OK    {result['topic_id']}  {location}")
        else:
            print(f"  FAIL  {result['topic_id']}  {result.get('error', 'unknown error')}")

    # Non-zero only when the whole batch failed — a partial batch is still a
    # useful morning, and failing CI on it would hide the videos that worked.
    return 0 if any(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
