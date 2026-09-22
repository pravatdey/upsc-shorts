"""
progress.json — the small file that survives across GitHub Actions runs.

The SQLite DB lives in `data/` which is gitignored and therefore wiped on every
CI run. This JSON file is committed back by the workflow, so it is the single
source of truth for "which topics have I already published?".
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from .logger import get_logger

logger = get_logger(__name__)

DEFAULT = {
    "serial": 0,          # running count of published Shorts
    "used_topic_ids": [],  # topics already turned into a Short
    "uploads": [],         # [{topic_id, title, video_id, url, date}]
    "last_run": None,
}


class ProgressStore:
    """Reads/writes progress.json with a forgiving, self-healing schema."""

    def __init__(self, path: str = "progress.json"):
        self.path = Path(path)
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT, used_topic_ids=[], uploads=[])
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"progress.json unreadable ({e}), starting fresh")
            return dict(DEFAULT, used_topic_ids=[], uploads=[])

        for key, default in DEFAULT.items():
            data.setdefault(key, default if not isinstance(default, list) else [])
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ---- accessors ----

    @property
    def used_topic_ids(self) -> List[str]:
        return list(self.data.get("used_topic_ids", []))

    @property
    def serial(self) -> int:
        return int(self.data.get("serial", 0))

    def mark_used(self, topic_id: str) -> None:
        """Reserve a topic so a later failure never re-picks it silently."""
        if topic_id not in self.data["used_topic_ids"]:
            self.data["used_topic_ids"].append(topic_id)

    def release(self, topic_id: str) -> None:
        """Give a topic back to the pool (generation failed before upload)."""
        if topic_id in self.data["used_topic_ids"]:
            self.data["used_topic_ids"].remove(topic_id)

    def record_upload(self, topic_id: str, title: str, video_id: str,
                      url: str, date: str) -> int:
        self.data["serial"] = self.serial + 1
        self.mark_used(topic_id)
        self.data["uploads"].append({
            "serial": self.data["serial"],
            "topic_id": topic_id,
            "title": title,
            "video_id": video_id,
            "url": url,
            "date": date,
        })
        # keep the file small — the DB holds the full history
        self.data["uploads"] = self.data["uploads"][-300:]
        return self.data["serial"]

    def set_last_run(self, iso_timestamp: str) -> None:
        self.data["last_run"] = iso_timestamp
