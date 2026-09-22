"""
Word-synced captions — the single biggest retention lever on Shorts.

Most Shorts are watched muted or half-watched, so the captions *are* the video
for a large share of viewers. Highlighting the word currently being spoken
(the "karaoke" pattern) keeps eyes locked to the centre of the frame, which is
why it is worth building properly rather than burning in a static subtitle.

Design notes:

* Words are grouped into short windows of a few words each. A window is what
  is on screen at one time; within it the spoken word is highlighted.
* Bands are rendered on demand and kept in a tiny LRU. Frames are produced in
  time order, so consecutive frames almost always hit the same cache entry —
  a full per-word cache would cost hundreds of megabytes for no gain.
* Each word is drawn individually so its x position is known. Devanagari
  shaping happens within a word, never across a space, so this is safe.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .fonts import FontBook
from .theme import Fonts, Layout, Palette, hex_to_rgb
from . import textfit
from src.content.models import ShortScript
from src.tts.base_tts import WordTiming
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CaptionWindow:
    words: List[WordTiming]
    start: float
    end: float

    def active_index(self, t: float) -> int:
        """Index of the word being spoken at time t; clamped to the window."""
        for i, word in enumerate(self.words):
            if t < word.end:
                return i
        return len(self.words) - 1


@dataclass
class _LaidOutWord:
    text: str
    x: int
    y: int
    width: int


@dataclass
class _Layout:
    words: List[_LaidOutWord] = field(default_factory=list)
    font: Optional[ImageFont.FreeTypeFont] = None
    height: int = 0


class CaptionBuilder:
    """Groups word timings into on-screen windows."""

    def __init__(self, fonts: FontBook, max_words: int = 5,
                 max_seconds: float = 2.6):
        self.fonts = fonts
        self.max_words = max_words
        self.max_seconds = max_seconds
        self._font = fonts.get("devanagari", Fonts.CAPTION)

    def build(self, words: List[WordTiming]) -> List[CaptionWindow]:
        if not words:
            return []

        max_width = Layout.CONTENT_WIDTH
        windows: List[CaptionWindow] = []
        current: List[WordTiming] = []

        for word in words:
            candidate = current + [word]
            too_many = len(candidate) > self.max_words
            too_long = (candidate[-1].end - candidate[0].start) > self.max_seconds
            too_wide = self._lines_needed(candidate, max_width) > Layout.CAPTION_MAX_LINES

            if current and (too_many or too_long or too_wide):
                windows.append(_window(current))
                current = [word]
            else:
                current = candidate

            # Never let a window straddle a sentence break. A caption reading
            # "...किया। यहाँ तापमान..." makes the viewer re-parse mid-sentence,
            # which is exactly the friction captions are meant to remove.
            if current and _ends_sentence(current[-1].text):
                windows.append(_window(current))
                current = []

        if current:
            windows.append(_window(current))

        logger.info(f"Captions: {len(words)} words in {len(windows)} windows")
        return windows

    def _lines_needed(self, words: List[WordTiming], max_width: int) -> int:
        text = " ".join(w.text for w in words)
        return max(1, len(textfit.wrap(text, self._font, max_width)))


class CaptionRenderer:
    """Renders the caption band as an RGBA overlay for a given moment."""

    CACHE_SIZE = 8

    def __init__(self, fonts: FontBook, accent: str):
        self.fonts = fonts
        self.accent = hex_to_rgb(accent)
        self._cache: "OrderedDict[Tuple[int, int], Image.Image]" = OrderedDict()
        self._layouts: List[_Layout] = []

    def prepare(self, windows: List[CaptionWindow]) -> None:
        """Lay out every window once, up front, so frame time stays cheap."""
        self._layouts = [self._layout_window(w) for w in windows]
        self._cache.clear()

    def band(self, window_index: int, active_index: int) -> Optional[Image.Image]:
        key = (window_index, active_index)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        if not (0 <= window_index < len(self._layouts)):
            return None

        image = self._render(self._layouts[window_index], active_index)
        self._cache[key] = image
        if len(self._cache) > self.CACHE_SIZE:
            self._cache.popitem(last=False)
        return image

    # ---- layout ----

    def _layout_window(self, window: CaptionWindow) -> _Layout:
        """
        Place every word of a window, shrinking the font until it fits the band.

        Words are positioned by advance width (`getlength`) rather than ink
        extents so spacing stays even regardless of ascenders and matras.
        """
        max_width = Layout.CONTENT_WIDTH
        max_height = Layout.CAPTION_BAND_HEIGHT - 40
        texts = [w.text for w in window.words]

        size = Fonts.CAPTION
        while size > Fonts.CAPTION_MIN:
            font = self.fonts.for_text(" ".join(texts), size)
            lines = _pack_lines(texts, font, max_width)
            lh = textfit.line_height(font)
            height = len(lines) * lh + max(0, len(lines) - 1) * Layout.CAPTION_LINE_GAP
            if len(lines) <= Layout.CAPTION_MAX_LINES and height <= max_height:
                return _place(lines, font, height)
            size -= 4

        font = self.fonts.for_text(" ".join(texts), Fonts.CAPTION_MIN)
        lines = _pack_lines(texts, font, max_width)[:Layout.CAPTION_MAX_LINES]
        lh = textfit.line_height(font)
        height = len(lines) * lh + max(0, len(lines) - 1) * Layout.CAPTION_LINE_GAP
        return _place(lines, font, height)

    # ---- rendering ----

    def _render(self, layout: _Layout, active_index: int) -> Image.Image:
        image = Image.new(
            "RGBA", (Layout.WIDTH, Layout.CAPTION_BAND_HEIGHT), (0, 0, 0, 0)
        )
        draw = ImageDraw.Draw(image)
        font = layout.font
        lh = textfit.line_height(font)

        # Centre the whole block vertically inside the band.
        offset_y = max(0, (Layout.CAPTION_BAND_HEIGHT - layout.height) // 2)

        idle = hex_to_rgb(Palette.CAPTION_IDLE)
        spoken = hex_to_rgb(Palette.CAPTION_SPOKEN)
        highlight_text = hex_to_rgb(Palette.CAPTION_HIGHLIGHT_TEXT)
        shadow = (0, 0, 0, 220)

        for i, word in enumerate(layout.words):
            x, y = word.x, word.y + offset_y

            if i == active_index:
                # Generous vertical padding: Devanagari marks (chandrabindu,
                # reph) sit above the nominal ascent and would otherwise touch
                # the highlight's edge.
                pad_x, pad_y = 16, 16
                draw.rounded_rectangle(
                    [x - pad_x, y - pad_y, x + word.width + pad_x, y + lh + pad_y],
                    radius=14, fill=(*self.accent, 255),
                )
                fill = highlight_text
                stroke_width = 0
                stroke_fill = None
            else:
                fill = spoken if i < active_index else idle
                stroke_width = 5
                stroke_fill = shadow

            draw.text((x, y), word.text, font=font, fill=fill, anchor="la",
                      stroke_width=stroke_width, stroke_fill=stroke_fill)

        return image


# ---- module helpers ----

def _window(words: List[WordTiming]) -> CaptionWindow:
    return CaptionWindow(words=list(words), start=words[0].start, end=words[-1].end)


def _ends_sentence(word: str) -> bool:
    """True if this token closes a sentence, in Latin or Devanagari punctuation."""
    return word.rstrip("\"')]}").endswith((".", "!", "?", "।", "॥"))


def _pack_lines(texts: List[str], font: ImageFont.FreeTypeFont,
                max_width: int) -> List[List[str]]:
    """Greedy line packing that keeps words as separate units."""
    space = font.getlength(" ")
    lines: List[List[str]] = []
    current: List[str] = []
    current_width = 0.0

    for text in texts:
        width = font.getlength(text)
        extra = width if not current else space + width
        if current and current_width + extra > max_width:
            lines.append(current)
            current, current_width = [text], width
        else:
            current.append(text)
            current_width += extra

    if current:
        lines.append(current)
    return lines


def _place(lines: List[List[str]], font: ImageFont.FreeTypeFont,
           height: int) -> _Layout:
    """Turn packed lines into absolute positions, each line centred."""
    space = font.getlength(" ")
    lh = textfit.line_height(font)
    placed: List[_LaidOutWord] = []

    y = 0
    for line in lines:
        widths = [font.getlength(text) for text in line]
        total = sum(widths) + space * max(0, len(line) - 1)
        x = (Layout.WIDTH - total) / 2
        for text, width in zip(line, widths):
            placed.append(_LaidOutWord(text=text, x=int(x), y=int(y), width=int(width)))
            x += width + space
        y += lh + Layout.CAPTION_LINE_GAP

    return _Layout(words=placed, font=font, height=height)


def align_beats(script: ShortScript, words: List[WordTiming],
                audio_duration: float) -> List[Tuple[float, float]]:
    """
    Map each beat onto a (start, end) slice of the audio.

    The narration handed to TTS is the beats joined by single spaces, so the
    engine's word sequence is the concatenation of each beat's words. When the
    counts agree we can cut exactly on those boundaries. Engines that tokenize
    slightly differently (Edge splits some punctuation) make the totals drift,
    so in that case the boundaries are scaled proportionally instead — a
    fraction of a second off at worst, and never misaligned overall.
    """
    counts = script.word_counts()
    total_expected = sum(counts)
    beat_count = len(counts)

    if total_expected <= 0 or not words:
        span = audio_duration / max(1, beat_count)
        return [(i * span, (i + 1) * span) for i in range(beat_count)]

    actual = len(words)
    if actual != total_expected:
        logger.info(
            f"Word count drift: script has {total_expected}, TTS reported "
            f"{actual}; scaling beat boundaries proportionally"
        )

    spans: List[Tuple[float, float]] = []
    cumulative = 0
    previous_index = 0

    for i, count in enumerate(counts):
        cumulative += count
        index = round(cumulative * actual / total_expected)
        index = max(previous_index + 1, min(actual, index))

        start = words[previous_index].start if previous_index < actual else audio_duration
        end = words[index - 1].end if index - 1 < actual else audio_duration

        if i == 0:
            start = 0.0
        if i == beat_count - 1:
            end = audio_duration

        spans.append((start, max(start + 0.2, end)))
        previous_index = index

    # Close any gap left between consecutive beats so no frame is unassigned.
    for i in range(len(spans) - 1):
        spans[i] = (spans[i][0], spans[i + 1][0])

    return spans
