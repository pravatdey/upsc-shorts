"""
Topic Bank — picks the next unused topics from config/topics.yaml.

Selection rules, in order:
  1. Never repeat a topic that progress.json already records as used.
  2. Spread the day's batch across different categories, so three Shorts
     posted the same morning don't all look like the same video.
  3. Keep the bank's authored order otherwise (it is roughly difficulty-sorted).

When every topic has been used the bank wraps around and starts a fresh cycle,
so the channel never stalls.
"""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .models import Topic
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TopicBank:
    def __init__(self, path: str = "config/topics.yaml"):
        self.path = Path(path)
        self.topics: List[Topic] = self._load()
        if not self.topics:
            raise RuntimeError(f"No topics found in {path}")
        logger.info(f"Topic bank loaded: {len(self.topics)} topics across "
                    f"{len(set(t.category for t in self.topics))} categories")

    def _load(self) -> List[Topic]:
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        topics: List[Topic] = []
        seen_ids = set()
        for entry in data.get("topics", []):
            topic_id = str(entry.get("id", "")).strip()
            title = str(entry.get("title", "")).strip()
            if not topic_id or not title:
                logger.warning(f"Skipping malformed topic entry: {entry}")
                continue
            if topic_id in seen_ids:
                logger.warning(f"Duplicate topic id '{topic_id}' ignored")
                continue
            seen_ids.add(topic_id)
            topics.append(Topic(
                id=topic_id,
                title=title,
                category=str(entry.get("category", "general")).strip(),
                angle=str(entry.get("angle", "")).strip(),
                keywords=[str(k) for k in entry.get("keywords", [])],
                difficulty=str(entry.get("difficulty", "medium")),
            ))
        return topics

    def by_id(self, topic_id: str) -> Optional[Topic]:
        return next((t for t in self.topics if t.id == topic_id), None)

    def pick(self, count: int, used_ids: List[str], seed: int = None) -> List[Topic]:
        """Return `count` topics to publish, spread across categories."""
        used = set(used_ids)
        available = [t for t in self.topics if t.id not in used]

        if len(available) < count:
            # Bank exhausted — start a new cycle rather than stopping the channel.
            logger.warning(
                f"Only {len(available)} unused topics left; wrapping around to "
                f"re-cycle the bank. Add more entries to config/topics.yaml."
            )
            recycled = [t for t in self.topics if t.id in used]
            available = available + recycled

        return self._spread_by_category(available, count, seed)

    @staticmethod
    def _spread_by_category(candidates: List[Topic], count: int,
                            seed: int = None) -> List[Topic]:
        """Round-robin over categories so a batch is visually/topically varied."""
        buckets: Dict[str, List[Topic]] = {}
        for topic in candidates:
            buckets.setdefault(topic.category, []).append(topic)

        # Rotate which category leads each day so the same one isn't always first.
        categories = sorted(buckets.keys())
        if seed is not None and categories:
            offset = seed % len(categories)
            categories = categories[offset:] + categories[:offset]

        picked: List[Topic] = []
        chosen_ids = set()
        while len(picked) < count:
            progressed = False
            for category in categories:
                if len(picked) >= count:
                    break
                for topic in buckets.get(category, []):
                    if topic.id not in chosen_ids:
                        picked.append(topic)
                        chosen_ids.add(topic.id)
                        progressed = True
                        break
            if not progressed:
                break

        if len(picked) < count:
            logger.warning(f"Requested {count} topics but only {len(picked)} available")
        return picked

    @property
    def total(self) -> int:
        return len(self.topics)
