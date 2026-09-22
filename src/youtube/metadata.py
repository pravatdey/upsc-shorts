"""
Metadata generator — titles, descriptions, tags and hashtags for Shorts.

Discovery on Shorts works differently from long-form. The title is short and
read at a glance, the first line of the description is what appears in search,
and hashtags meaningfully affect which feed a Short is tested in. So the
hashtag set is assembled deliberately: a few always-on channel tags, a
category-specific pool, and tags derived from the topic itself.
"""

import re
from typing import Any, Dict, List

import yaml

from src.content.models import ShortScript
from src.utils.logger import get_logger

logger = get_logger(__name__)

TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
# YouTube rejects uploads carrying more than 15 hashtags anywhere in the metadata.
MAX_HASHTAGS = 14


class MetadataGenerator:
    def __init__(self, config_path: str = "config/youtube_config.yaml"):
        self.config = self._load(config_path)

    @staticmethod
    def _load(path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not load {path}: {e}")
            return {}

    def generate(self, script: ShortScript, serial: int) -> Dict[str, Any]:
        meta = self.config.get("metadata", {})
        hashtags = self._hashtags(script)

        return {
            "title": self._title(script, hashtags),
            "description": self._description(script, hashtags, serial),
            "tags": self._tags(script),
            "category_id": str(meta.get("category_id", "27")),
            "made_for_kids": bool(meta.get("made_for_kids", False)),
            "language": meta.get("language", "hi"),
            "hashtags": hashtags,
        }

    # ---- title ----

    def _title(self, script: ShortScript, hashtags: List[str]) -> str:
        """
        Curiosity title plus #Shorts, trimmed to fit.

        #Shorts in the title is the clearest signal to YouTube about format,
        so it is reserved space — the headline is what gets cut if needed.
        """
        required = "#Shorts"
        extra = [tag for tag in hashtags if tag.lower() not in ("#shorts",)][:2]
        suffix = " ".join([required] + extra)

        headline = re.sub(r"\s+", " ", script.title).strip().rstrip(".|-")
        budget = TITLE_LIMIT - len(suffix) - 1

        if len(headline) > budget:
            # Trim on a word boundary so the title never ends mid-word.
            headline = headline[:budget].rsplit(" ", 1)[0].rstrip(",;:-")

        return f"{headline} {suffix}".strip()

    # ---- description ----

    def _description(self, script: ShortScript, hashtags: List[str],
                     serial: int) -> str:
        meta = self.config.get("metadata", {})
        blocks: List[str] = []

        hook = next((b.narration for b in script.beats if b.narration), script.title)
        blocks.append(hook.strip())

        if script.exam_note:
            label = meta.get("exam_note_label", "Exam relevance:")
            blocks.append(f"{label} {script.exam_note}")

        if script.engagement_question:
            prompt = meta.get("comment_prompt", "Comment your answer below:")
            blocks.append(f"{prompt}\n{script.engagement_question}")

        body = meta.get("description_body", "").strip()
        if body:
            blocks.append(body.format(
                topic=script.topic.title,
                category=script.topic.category_display,
                serial=serial,
            ))

        blocks.append(" ".join(hashtags))
        return "\n\n".join(b for b in blocks if b.strip())[:DESCRIPTION_LIMIT]

    # ---- tags & hashtags ----

    def _tags(self, script: ShortScript) -> List[str]:
        meta = self.config.get("metadata", {})
        base = [str(t) for t in meta.get("base_tags", [])]
        category_tags = [
            str(t) for t in
            self.config.get("category_tags", {}).get(script.topic.category, [])
        ]
        topic_tags = [script.topic.title.lower()] + [k.lower() for k in script.keywords]

        return _dedupe(base + category_tags + topic_tags)

    def _hashtags(self, script: ShortScript) -> List[str]:
        pools = self.config.get("hashtags", {})
        always = [str(t) for t in pools.get("always", [])]
        category = [str(t) for t in pools.get("by_category", {}).get(script.topic.category, [])]
        topic = [_to_hashtag(k) for k in script.keywords[:4]]
        topic = [t for t in topic if t]

        merged = _dedupe(always + category + topic, lower=True)
        return merged[:MAX_HASHTAGS]


# ---- helpers ----

def _dedupe(values: List[str], lower: bool = False) -> List[str]:
    seen = set()
    result = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value.lower() if lower else value)
    return result


def _to_hashtag(keyword: str) -> str:
    """
    Turn a keyword into a valid hashtag.

    Hashtags cannot contain spaces or punctuation; anything left shorter than
    three characters is dropped rather than posted as noise.
    """
    cleaned = re.sub(r"[^\wऀ-ॿ]+", "", keyword)
    return f"#{cleaned}" if len(cleaned) >= 3 else ""
