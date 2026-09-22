"""
Visual system for vertical Shorts.

Two things drive every number here:

1. **The Shorts safe area.** YouTube's own UI covers the bottom ~22% (title,
   channel, description) and the right ~13% (like/comment/share rail). Anything
   important that lands there is simply not seen, so the layout keeps all text
   inside x 70..930 and y 150..1500.

2. **Phone-sized legibility.** A Short is watched on a 6-inch screen, often
   muted with captions carrying the message. Type is therefore much larger
   relative to frame than it would be for 16:9.
"""

from typing import Tuple


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


class Layout:
    WIDTH = 1080
    HEIGHT = 1920

    MARGIN_X = 70
    CONTENT_WIDTH = WIDTH - 2 * MARGIN_X      # 940

    # Top furniture
    PROGRESS_BAR_HEIGHT = 9
    TOP_BAR_Y = 40
    TOP_BAR_HEIGHT = 56

    # Headline block — the big text that carries the beat
    KICKER_Y = 290
    HEADLINE_TOP = 380
    HEADLINE_BOTTOM = 900
    HEADLINE_LINE_GAP = 22

    # Caption band — sits in the lower-middle, above YouTube's own chrome.
    # Everything must stay above ~1470; below that the Shorts UI covers it.
    CAPTION_BAND_TOP = 980
    CAPTION_BAND_HEIGHT = 420
    CAPTION_LINE_GAP = 18
    CAPTION_MAX_LINES = 3

    # Beat progress dots
    DOTS_Y = 1450

    CARD_RADIUS = 28
    PILL_RADIUS = 26


class Fonts:
    HEADLINE = 92
    HEADLINE_MIN = 54          # auto-shrink floor before we wrap to more lines
    KICKER = 40
    CAPTION = 64
    CAPTION_MIN = 46
    BRAND = 34
    PILL = 30
    FOOTER = 30
    THUMB_HEADLINE = 104


class Palette:
    """
    A per-category accent. Three Shorts posted the same morning read as three
    different videos in the feed instead of one repeated template.
    """

    BG_TOP = "#080B14"
    BG_BOTTOM = "#0E1426"

    WHITE = "#FFFFFF"
    TEXT_PRIMARY = "#F2F6FF"
    TEXT_SECONDARY = "#A9B7D0"
    TEXT_DIM = "#6B7A94"
    SHADOW = "#000000"

    ACCENTS = {
        "geopolitics":           ("#FF4D6D", "#12040A"),
        "international_relations": ("#FF8A3D", "#140A03"),
        "polity":                ("#00D4FF", "#03101A"),
        "economy":               ("#2BE08A", "#031410"),
        "environment":           ("#7DD93B", "#08140A"),
        "history":               ("#FFC93C", "#151003"),
        "geography":             ("#4D9BFF", "#030C1A"),
        "science_tech":          ("#A855FF", "#0D0418"),
        "schemes":               ("#FF5EC7", "#160516"),
        "current_affairs":       ("#00E5D0", "#02140F"),
    }

    DEFAULT_ACCENT = ("#00D4FF", "#03101A")

    # Caption colours
    CAPTION_IDLE = "#E8EEF9"
    CAPTION_SPOKEN = "#8FA0BC"
    CAPTION_HIGHLIGHT_TEXT = "#0A0E18"

    @classmethod
    def accent(cls, category: str) -> str:
        return cls.ACCENTS.get(category, cls.DEFAULT_ACCENT)[0]

    @classmethod
    def tint(cls, category: str) -> str:
        """Very dark version of the accent, used to tint the background."""
        return cls.ACCENTS.get(category, cls.DEFAULT_ACCENT)[1]


# Kind-specific styling for the kicker strip above the headline.
KIND_STYLE = {
    "hook":    {"label": "",          "color": None},
    "context": {"label": "BACKGROUND", "color": Palette.TEXT_SECONDARY},
    "fact":    {"label": "FACT",       "color": None},
    "key":     {"label": "EXAM POINT", "color": "#FFC93C"},
    "cta":     {"label": "",           "color": None},
}
