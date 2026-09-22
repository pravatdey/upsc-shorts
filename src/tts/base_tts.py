"""
Abstract TTS interface shared by the Gemini and Edge engines.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TTSVoice:
    id: str
    name: str
    language: str
    provider: str


@dataclass
class WordTiming:
    """When a single word is spoken, in seconds from the start of the audio."""
    text: str
    start: float
    end: float


@dataclass
class TTSResult:
    audio_path: str
    duration: float
    voice: TTSVoice
    success: bool
    words: List[WordTiming] = field(default_factory=list)
    error: Optional[str] = None


class BaseTTS(ABC):
    """
    Common text handling for every engine.

    `preprocess` is deliberately shared: the caption builder tokenizes the same
    cleaned string the engine spoke, so both sides agree on what "the words"
    are. Changing it on one side only would desynchronize the captions.
    """

    @staticmethod
    def preprocess(text: str) -> str:
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"^\s*[▸♦→•\-\*]+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"#\w+", "", text)
        text = re.sub(r"[✔✗✓✕→←↑↓■□●○◆◇★☆]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """The one true tokenizer. Must match what timings are produced against."""
        return re.findall(r"\S+", text)

    @abstractmethod
    async def synthesize(self, text: str, output_path: str,
                         voice: str = None, language: str = None) -> TTSResult:
        ...


# Devanagari combining marks (matras, virama, nukta, anusvara). These attach to
# a preceding consonant rather than adding a syllable, so they should not
# inflate a word's estimated spoken length.
_COMBINING = re.compile(r"[ऀ-ःऺ-ॏ॑-ॗॢ-ॣ]")


def estimate_word_timings(text: str, total_duration: float) -> List[WordTiming]:
    """
    Distribute a known total duration across words by estimated spoken length.

    Used by engines that return audio but no word boundaries (Gemini). Weighting
    by syllable-bearing characters — ignoring Devanagari matras, which modify a
    consonant rather than adding a beat — tracks real speech noticeably better
    for Hindi than raw character count does.
    """
    words = BaseTTS.tokenize(text)
    if not words or total_duration <= 0:
        return []

    # +1.2 approximates the pause between words, which raw length misses.
    weights = [max(1.0, len(_COMBINING.sub("", w))) + 1.2 for w in words]
    total_weight = sum(weights)

    timings: List[WordTiming] = []
    cursor = 0.0
    for word, weight in zip(words, weights):
        span = total_duration * (weight / total_weight)
        timings.append(WordTiming(text=word, start=cursor, end=cursor + span))
        cursor += span
    return timings
