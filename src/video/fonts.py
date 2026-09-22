"""
Font resolution for mixed Devanagari / Latin rendering.

Two problems this module exists to solve:

1. **Glyph coverage.** Arial and DejaVu have no Devanagari glyphs; asking them
   to draw Hindi produces a row of empty boxes. So Devanagari text has to be
   routed to a font that actually covers the script, per string.

2. **Complex-script shaping.** Devanagari needs reordering and ligature
   substitution (matras that visually precede the consonant they follow in
   logical order, conjuncts, and so on). Pillow only does that through the
   Raqm layout engine. Without Raqm the text renders, but incorrectly.
   We select Raqm when it is compiled in and warn loudly when it is not.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont, features

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# (path, face index). The index matters for TrueType *collections*: Windows
# ships Nirmala UI as a single Nirmala.ttc holding six faces, and only index 1
# is the bold weight we want. Asking for index 0 silently gives the regular
# face, which looks thin and washed out at Shorts sizes.
#
# Searched in order. A font dropped into assets/fonts/ always wins, so the
# channel's look can be changed without touching code.
DEVANAGARI_CANDIDATES = [
    ("assets/fonts/NotoSansDevanagari-Bold.ttf", 0),
    ("assets/fonts/devanagari-bold.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf", 0),
    ("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf", 0),
    ("C:/Windows/Fonts/Nirmala.ttc", 1),      # Nirmala UI Bold
    ("C:/Windows/Fonts/NirmalaB.ttf", 0),
    ("C:/Windows/Fonts/Nirmala.ttf", 0),
    ("C:/Windows/Fonts/mangalb.ttf", 0),
    ("C:/Windows/Fonts/Mangal.ttf", 0),
]

LATIN_CANDIDATES = [
    ("assets/fonts/Inter-Bold.ttf", 0),
    ("assets/fonts/Montserrat-Bold.ttf", 0),
    ("assets/fonts/latin-bold.ttf", 0),
    ("C:/Windows/Fonts/arialbd.ttf", 0),
    ("C:/Windows/Fonts/segoeuib.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", 0),
]


def has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI.search(text))


class FontBook:
    """Caches resolved fonts by (script, size)."""

    def __init__(self):
        self._cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

        self._raqm = features.check("raqm")
        self._layout = (
            ImageFont.Layout.RAQM if self._raqm else ImageFont.Layout.BASIC
        )

        self._devanagari = _first_usable(DEVANAGARI_CANDIDATES)
        self._latin = _first_usable(LATIN_CANDIDATES)

        if self._devanagari:
            logger.info(f"Devanagari font: {self.devanagari_path}")
        else:
            logger.warning(
                "No Devanagari font found. Hindi text will render as empty boxes. "
                "Install fonts-noto-devanagari, or drop a .ttf at "
                "assets/fonts/NotoSansDevanagari-Bold.ttf"
            )

        if self._latin:
            logger.info(f"Latin font: {self.latin_path}")
        else:
            logger.warning("No Latin font found; falling back to Pillow's default")

        if not self._raqm:
            logger.warning(
                "Pillow was built without Raqm. Devanagari matras and conjuncts "
                "may render in the wrong order. Install libraqm for correct shaping."
            )

    # ---- introspection ----

    @property
    def devanagari_path(self) -> Optional[str]:
        return self._devanagari[0] if self._devanagari else None

    @property
    def latin_path(self) -> Optional[str]:
        return self._latin[0] if self._latin else None

    @property
    def raqm_available(self) -> bool:
        return self._raqm

    # ---- lookup ----

    def for_text(self, text: str, size: int) -> ImageFont.FreeTypeFont:
        """Pick a font that can actually draw this string."""
        script = "devanagari" if has_devanagari(text) else "latin"
        return self.get(script, size)

    def get(self, script: str, size: int) -> ImageFont.FreeTypeFont:
        size = max(8, int(size))
        key = (script, size)
        if key in self._cache:
            return self._cache[key]

        chosen = self._devanagari if script == "devanagari" else self._latin
        # Noto Devanagari and Nirmala both cover Latin, so either is a safe
        # stand-in when the preferred one is missing.
        chosen = chosen or self._devanagari or self._latin

        font = ImageFont.load_default()
        if chosen:
            path, index = chosen
            try:
                font = ImageFont.truetype(path, size, index=index,
                                          layout_engine=self._layout)
            except Exception as e:
                logger.warning(f"Could not load {path}#{index} at {size}px ({e})")

        self._cache[key] = font
        return font


def _first_usable(candidates: List[Tuple[str, int]]) -> Optional[Tuple[str, int]]:
    """First candidate that exists on disk and that Pillow can actually open."""
    for path, index in candidates:
        if not Path(path).exists():
            continue
        try:
            ImageFont.truetype(path, 12, index=index)
            return (path, index)
        except Exception as e:
            logger.warning(f"Font {path}#{index} exists but will not load: {e}")

    # Also honour a font installed by name on the system font path.
    for path, index in candidates:
        name = os.path.basename(path)
        try:
            ImageFont.truetype(name, 12, index=index)
            return (name, index)
        except Exception:
            continue
    return None
