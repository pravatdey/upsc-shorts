"""
Script Writer — turns a Topic into a ready-to-render ShortScript.

Beyond calling the LLM this module does the boring-but-critical work of making
the result *safe to render*: JSON salvaged from chatty responses, beats coerced
into the expected order, headlines truncated, and narration trimmed to a word
budget so the finished Short stays under YouTube's 60-second Shorts ceiling.
"""

import json
import re
from typing import Any, Dict, List, Optional

from .models import Beat, BeatKind, ShortScript, Topic
from .prompts import (
    SCRIPT_PROMPT,
    SYSTEM_PROMPT_ENGLISH,
    SYSTEM_PROMPT_HINDI,
)
from src.llm.client import LLMClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Beats in the order they must appear, and how many of each we expect.
EXPECTED_ORDER = [
    BeatKind.HOOK,
    BeatKind.CONTEXT,
    BeatKind.FACT,
    BeatKind.FACT,
    BeatKind.FACT,
    BeatKind.KEY,
    BeatKind.CTA,
]


class ScriptWriter:
    def __init__(self, llm: LLMClient, language: str = "hindi",
                 target_seconds: int = 50, words_per_second: float = 2.6):
        self.llm = llm
        self.language = language.lower()
        self.target_seconds = target_seconds
        self.words_per_second = words_per_second

        # Narration length is the only real lever on video duration.
        self.target_words = int(target_seconds * words_per_second)
        self.min_words = int(self.target_words * 0.80)
        self.max_words = int(self.target_words * 1.10)

        logger.info(
            f"ScriptWriter ready: language={self.language}, "
            f"target={target_seconds}s (~{self.target_words} words)"
        )

    # ---- public API ----

    def write(self, topic: Topic, max_attempts: int = 3) -> ShortScript:
        prompt = self._build_prompt(topic)
        system = SYSTEM_PROMPT_HINDI if self.language == "hindi" else SYSTEM_PROMPT_ENGLISH

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Writing script for '{topic.title}' (attempt {attempt})")
                raw = self.llm.generate(
                    prompt=prompt, system_prompt=system,
                    max_tokens=2500, temperature=0.85,
                )
                data = _parse_json(raw)
                if not data:
                    logger.warning("Response was not parseable JSON")
                    continue

                script = self._build_script(topic, data)
                if script:
                    logger.info(
                        f"Script ready: {len(script.beats)} beats, "
                        f"{script.total_words()} words "
                        f"(~{script.total_words() / self.words_per_second:.0f}s)"
                    )
                    return script

                logger.warning("Parsed JSON did not contain usable beats")

            except Exception as e:
                logger.error(f"Script generation failed (attempt {attempt}): {e}")

        logger.warning(f"Falling back to a template script for '{topic.title}'")
        return self._fallback(topic)

    # ---- prompt ----

    def _build_prompt(self, topic: Topic) -> str:
        headline_lang = "in Hindi (Devanagari)" if self.language == "hindi" else "in English"
        # Budgets sum to roughly target_words; the LLM overshoots slightly, which
        # _enforce_budget then trims down.
        return SCRIPT_PROMPT.format(
            duration=self.target_seconds,
            title=topic.title,
            category=topic.category_display,
            angle=topic.angle or "Make it surprising and exam-relevant",
            keywords=", ".join(topic.keywords) if topic.keywords else topic.title,
            hook_words=max(10, int(self.target_words * 0.10)),
            context_words=max(12, int(self.target_words * 0.14)),
            fact_words=max(14, int(self.target_words * 0.16)),
            key_words=max(12, int(self.target_words * 0.14)),
            cta_words=max(10, int(self.target_words * 0.12)),
            min_words=self.min_words,
            max_words=self.max_words,
            headline_lang=headline_lang,
        )

    # ---- response -> ShortScript ----

    def _build_script(self, topic: Topic, data: Dict[str, Any]) -> Optional[ShortScript]:
        raw_beats = data.get("beats") or []
        if not isinstance(raw_beats, list) or not raw_beats:
            return None

        beats = self._coerce_beats(raw_beats)
        if len(beats) < 3:
            return None

        self._enforce_budget(beats)
        self._number_facts(beats)

        title = _clean(str(data.get("title") or topic.title))[:90]
        keywords = [_clean(str(k)) for k in (data.get("keywords") or []) if str(k).strip()]

        return ShortScript(
            topic=topic,
            title=title,
            beats=beats,
            exam_note=_clean(str(data.get("exam_note") or "")),
            engagement_question=_clean(str(data.get("engagement_question") or "")),
            keywords=(keywords or topic.keywords)[:15],
        )

    def _coerce_beats(self, raw_beats: List[Any]) -> List[Beat]:
        """Map whatever the model returned onto our expected beat sequence."""
        parsed: List[Beat] = []
        for raw in raw_beats:
            if not isinstance(raw, dict):
                continue
            narration = _clean(str(raw.get("narration") or ""))
            if not narration:
                continue
            kind = _coerce_kind(str(raw.get("kind") or ""))
            headline = _clean(str(raw.get("headline") or ""))
            if not headline:
                headline = _headline_from(narration)
            parsed.append(Beat(kind=kind, headline=_shorten_headline(headline),
                               narration=narration))

        if not parsed:
            return []

        # Guarantee the sequence opens on a hook and closes on a CTA — the two
        # beats that carry the most weight for retention and follows.
        parsed[0].kind = BeatKind.HOOK
        parsed[-1].kind = BeatKind.CTA
        return parsed[:len(EXPECTED_ORDER)]

    def _enforce_budget(self, beats: List[Beat]) -> None:
        """
        Trim narration if the model overshot.

        Going over budget means the Short exceeds 60 seconds and loses its place
        in the Shorts feed, so this is a correctness concern, not a style one.
        We trim proportionally from the longest body beats and never touch the
        hook or the CTA.
        """
        total = sum(len(re.findall(r"\S+", b.narration)) for b in beats)
        if total <= self.max_words:
            return

        excess = total - self.max_words
        logger.info(f"Narration is {total} words, trimming {excess} to fit budget")

        trimmable = [b for b in beats if b.kind in (BeatKind.FACT, BeatKind.CONTEXT, BeatKind.KEY)]
        trimmable.sort(key=lambda b: len(b.narration), reverse=True)

        for beat in trimmable:
            if excess <= 0:
                break
            sentences = _split_sentences(beat.narration)
            # Drop trailing sentences while the beat keeps at least one.
            while len(sentences) > 1 and excess > 0:
                dropped = sentences.pop()
                excess -= len(re.findall(r"\S+", dropped))
            beat.narration = " ".join(sentences).strip()

        if excess > 0:
            # Still long: hard-truncate the longest beat at a word boundary.
            longest = max(beats, key=lambda b: len(b.narration))
            words = re.findall(r"\S+", longest.narration)
            keep = max(6, len(words) - excess)
            longest.narration = " ".join(words[:keep])

    @staticmethod
    def _number_facts(beats: List[Beat]) -> None:
        fact_total = sum(1 for b in beats if b.kind == BeatKind.FACT)
        counter = 0
        for beat in beats:
            if beat.kind == BeatKind.FACT:
                counter += 1
                beat.index = counter
                beat.total_facts = fact_total

    # ---- fallback ----

    def _fallback(self, topic: Topic) -> ShortScript:
        """
        A never-fails script so a bad LLM day still produces a publishable Short.

        Intentionally generic: it frames the topic and points at the pinned
        comment rather than inventing facts that could be wrong.
        """
        if self.language == "hindi":
            beats = [
                Beat(BeatKind.HOOK, topic.title,
                     f"{topic.title} के बारे में वो बात जो ज़्यादातर अभ्यर्थी नहीं जानते।"),
                Beat(BeatKind.CONTEXT, "क्यों ज़रूरी",
                     f"{topic.title} {topic.category_display} का वो हिस्सा है जो हर साल "
                     f"प्रारंभिक और मुख्य परीक्षा दोनों में लौटकर आता है।"),
                Beat(BeatKind.KEY, "परीक्षा में",
                     f"{topic.angle or topic.title} को समझ लीजिए तो इससे जुड़े सवाल "
                     f"सीधे हल हो जाते हैं।"),
                Beat(BeatKind.CTA, "फॉलो करें",
                     "आपका जवाब कमेंट में लिखिए, और रोज़ ऐसे ही यूपीएससी शॉर्ट्स के लिए फॉलो कीजिए।"),
            ]
            question = f"{topic.title} पर आपका क्या विचार है?"
        else:
            beats = [
                Beat(BeatKind.HOOK, topic.title,
                     f"Here is what most aspirants get wrong about {topic.title}."),
                Beat(BeatKind.CONTEXT, "Why it matters",
                     f"{topic.title} sits in {topic.category_display}, a section that "
                     f"returns in both Prelims and Mains almost every year."),
                Beat(BeatKind.KEY, "In the exam",
                     f"Understand {topic.angle or topic.title} and the questions built "
                     f"on it solve themselves."),
                Beat(BeatKind.CTA, "Follow",
                     "Drop your answer in the comments, and follow for a new UPSC short every day."),
            ]
            question = f"What is your take on {topic.title}?"

        self._number_facts(beats)
        return ShortScript(
            topic=topic,
            title=topic.title,
            beats=beats,
            exam_note="",
            engagement_question=question,
            keywords=topic.keywords,
        )


# ---- helpers ----

_KIND_ALIASES = {
    "hook": BeatKind.HOOK, "opening": BeatKind.HOOK, "intro": BeatKind.HOOK,
    "context": BeatKind.CONTEXT, "background": BeatKind.CONTEXT, "setup": BeatKind.CONTEXT,
    "fact": BeatKind.FACT, "point": BeatKind.FACT, "body": BeatKind.FACT,
    "key": BeatKind.KEY, "takeaway": BeatKind.KEY, "exam": BeatKind.KEY,
    "cta": BeatKind.CTA, "outro": BeatKind.CTA, "ending": BeatKind.CTA,
}


def _coerce_kind(value: str) -> BeatKind:
    token = re.sub(r"[^a-z]", "", value.lower())
    for alias, kind in _KIND_ALIASES.items():
        if alias in token:
            return kind
    return BeatKind.FACT


def _clean(text: str) -> str:
    """Strip anything the voice would read literally or the renderer would choke on."""
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*[\-\*•▸→]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    # Emoji and decorative symbols
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    """Split on Latin and Devanagari sentence enders, keeping the punctuation."""
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _shorten_headline(text: str, max_words: int = 5, max_chars: int = 34) -> str:
    text = text.rstrip(".!?।")
    words = re.findall(r"\S+", text)
    if len(words) > max_words:
        words = words[:max_words]
    result = " ".join(words)
    return result[:max_chars].strip()


def _headline_from(narration: str) -> str:
    return _shorten_headline(" ".join(re.findall(r"\S+", narration)[:5]))


def _parse_json(response: str) -> Optional[Dict[str, Any]]:
    """Recover a JSON object from a response that may be wrapped in prose or fences."""
    candidates = [response]

    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))

    start, end = response.find("{"), response.rfind("}")
    if start != -1 and end > start:
        candidates.append(response[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    logger.error(f"Could not parse JSON from response: {response[:300]}")
    return None
