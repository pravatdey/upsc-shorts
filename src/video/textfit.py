"""
Text measuring, wrapping and shadowed drawing.

Everything on a Short is generated text of unpredictable length, so nothing can
rely on a fixed font size. `fit_block` shrinks until the text fits its box,
which is what keeps a five-word Hindi headline and a two-word English one both
looking deliberate.
"""

from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

from .fonts import FontBook

# One shared scratch surface for measurement — creating a Draw per call is the
# single hottest cost in caption rendering.
_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def measure(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """Width and height of a single line."""
    if not text:
        return 0, 0
    left, top, right, bottom = _MEASURE.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def line_height(font: ImageFont.FreeTypeFont) -> int:
    """
    Consistent line height regardless of which glyphs a line happens to use.

    Measuring per-line makes Devanagari lines with tall matras jump around, so
    we take the font's own ascent/descent instead.
    """
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except Exception:
        return measure("Ag", font)[1]


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Greedy word wrap. Words longer than the line get their own line."""
    words = text.split()
    if not words:
        return []

    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if measure(candidate, font)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_block(text: str, fonts: FontBook, max_width: int, max_height: int,
              start_size: int, min_size: int, line_gap: int,
              max_lines: int = 6) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    """
    Largest font size at which `text` wraps inside (max_width, max_height).

    Returns the chosen font and its wrapped lines. At `min_size` we accept the
    result and truncate rather than shrinking into unreadability.
    """
    size = start_size
    font = fonts.for_text(text, size)
    lines = wrap(text, font, max_width)

    while size > min_size:
        font = fonts.for_text(text, size)
        lines = wrap(text, font, max_width)
        block_height = len(lines) * line_height(font) + max(0, len(lines) - 1) * line_gap
        if len(lines) <= max_lines and block_height <= max_height:
            return font, lines
        size -= 4

    font = fonts.for_text(text, min_size)
    lines = wrap(text, font, max_width)[:max_lines]
    return font, lines


def draw_line(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str,
              font: ImageFont.FreeTypeFont, fill, anchor: str = "la",
              shadow: Tuple[int, int, int, int] = None,
              shadow_offset: Tuple[int, int] = (0, 4),
              stroke_width: int = 0, stroke_fill=None) -> None:
    """Draw one line, optionally with a drop shadow behind it."""
    if shadow:
        draw.text(
            (xy[0] + shadow_offset[0], xy[1] + shadow_offset[1]),
            text, font=font, fill=shadow, anchor=anchor,
            stroke_width=stroke_width, stroke_fill=shadow,
        )
    draw.text(xy, text, font=font, fill=fill, anchor=anchor,
              stroke_width=stroke_width, stroke_fill=stroke_fill)


def draw_block(draw: ImageDraw.ImageDraw, lines: List[str],
               font: ImageFont.FreeTypeFont, center_x: int, top_y: int,
               fill, line_gap: int, shadow=None, stroke_width: int = 0,
               stroke_fill=None) -> int:
    """Draw centred, wrapped lines top-down. Returns the y below the block."""
    lh = line_height(font)
    y = top_y
    for line in lines:
        draw_line(draw, (center_x, y), line, font, fill, anchor="ma",
                  shadow=shadow, stroke_width=stroke_width, stroke_fill=stroke_fill)
        y += lh + line_gap
    return y - line_gap if lines else top_y
