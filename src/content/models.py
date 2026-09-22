"""
Data models for topics and generated Short scripts.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class BeatKind(str, Enum):
    """The narrative role a beat plays. Drives card styling and pacing."""
    HOOK = "hook"        # 0-4s   stop the scroll
    CONTEXT = "context"  # setup / why it matters
    FACT = "fact"        # the punchy body facts
    KEY = "key"          # the exam-relevant takeaway
    CTA = "cta"          # follow / comment


@dataclass
class Topic:
    """One entry from the topic bank."""
    id: str
    title: str
    category: str
    angle: str = ""                                 # the viral framing to use
    keywords: List[str] = field(default_factory=list)
    difficulty: str = "medium"

    @property
    def category_display(self) -> str:
        return self.category.replace("_", " ").title()


@dataclass
class Beat:
    """A single on-screen card + the narration spoken over it."""
    kind: BeatKind
    headline: str      # 2-6 words, rendered LARGE on the card
    narration: str     # what the voice says over this card
    index: int = 0
    total_facts: int = 0

    @property
    def kicker(self) -> str:
        """Small label above the headline."""
        return {
            BeatKind.HOOK: "",
            BeatKind.CONTEXT: "BACKGROUND",
            BeatKind.FACT: f"FACT {self.index}" if self.index else "FACT",
            BeatKind.KEY: "EXAM POINT",
            BeatKind.CTA: "",
        }[self.kind]


@dataclass
class ShortScript:
    """A complete, ready-to-render Short."""
    topic: Topic
    title: str
    beats: List[Beat] = field(default_factory=list)
    exam_note: str = ""
    engagement_question: str = ""
    hashtags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def narration_text(self) -> str:
        """
        Full narration for TTS.

        Beats are joined with a plain space so the resulting word sequence is
        exactly the concatenation of each beat's words — that is what lets
        CaptionBuilder map word timings back onto beat boundaries.
        """
        return " ".join(b.narration.strip() for b in self.beats if b.narration.strip())

    def word_counts(self) -> List[int]:
        """Words per beat, in the same tokenization the caption builder uses."""
        return [len(re.findall(r"\S+", b.narration.strip())) for b in self.beats]

    def total_words(self) -> int:
        return sum(self.word_counts())
