"""
Card Renderer — the static 1080x1920 background for one beat.

Each beat gets one card. Captions, the progress bar and the zoom are animated
on top of it at frame time by the composer, so a card is rendered once per beat
(six or seven per video) rather than once per frame.
"""

from typing import Tuple

from PIL import Image, ImageDraw, ImageFilter

from .fonts import FontBook
from .theme import Fonts, KIND_STYLE, Layout, Palette, hex_to_rgb
from . import textfit
from src.content.models import Beat, BeatKind, ShortScript
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CardRenderer:
    def __init__(self, brand: str = "UPSC SHORTS", fonts: FontBook = None):
        self.brand = brand
        self.fonts = fonts or FontBook()

    # ---- public ----

    def render(self, script: ShortScript, beat: Beat, beat_index: int,
               beat_count: int) -> Image.Image:
        category = script.topic.category
        accent = Palette.accent(category)
        image = self._background(category)
        draw = ImageDraw.Draw(image)

        self._draw_top_bar(draw, script, accent)
        self._draw_kicker(draw, beat, accent)
        self._draw_headline(draw, beat, accent)
        self._draw_beat_dots(draw, beat_index, beat_count, accent)

        if beat.kind == BeatKind.CTA:
            self._draw_follow_pill(draw, accent)

        return image

    def render_thumbnail(self, script: ShortScript) -> Image.Image:
        """
        A 1080x1920 cover frame.

        Shorts usually autoplay without a thumbnail, but YouTube does show one
        in search, on the channel grid and in suggestions — which is exactly
        where a strong cover earns extra views.
        """
        category = script.topic.category
        accent = Palette.accent(category)
        image = self._background(category)
        draw = ImageDraw.Draw(image)

        hook = next((b for b in script.beats if b.kind == BeatKind.HOOK), script.beats[0])

        self._draw_top_bar(draw, script, accent)

        font, lines = textfit.fit_block(
            hook.headline or script.title, self.fonts,
            max_width=Layout.CONTENT_WIDTH,
            max_height=760,
            start_size=Fonts.THUMB_HEADLINE,
            min_size=Fonts.HEADLINE_MIN,
            line_gap=Layout.HEADLINE_LINE_GAP,
            max_lines=4,
        )
        textfit.draw_block(
            draw, lines, font, Layout.WIDTH // 2, 640,
            fill=hex_to_rgb(Palette.WHITE),
            line_gap=Layout.HEADLINE_LINE_GAP,
            shadow=(0, 0, 0, 255), stroke_width=3,
            stroke_fill=hex_to_rgb(Palette.SHADOW),
        )

        # Accent rule under the headline
        rule_y = 1180
        draw.rounded_rectangle(
            [Layout.WIDTH // 2 - 140, rule_y, Layout.WIDTH // 2 + 140, rule_y + 10],
            radius=5, fill=hex_to_rgb(accent),
        )
        return image

    # ---- background ----

    def _background(self, category: str) -> Image.Image:
        """Vertical gradient tinted toward the category accent, plus soft glows."""
        accent_rgb = hex_to_rgb(Palette.accent(category))
        top = hex_to_rgb(Palette.BG_TOP)
        bottom = hex_to_rgb(Palette.tint(category))

        image = Image.new("RGB", (Layout.WIDTH, Layout.HEIGHT))
        draw = ImageDraw.Draw(image)
        for y in range(Layout.HEIGHT):
            ratio = y / Layout.HEIGHT
            draw.line(
                [(0, y), (Layout.WIDTH, y)],
                fill=(
                    int(top[0] + (bottom[0] - top[0]) * ratio),
                    int(top[1] + (bottom[1] - top[1]) * ratio),
                    int(top[2] + (bottom[2] - top[2]) * ratio),
                ),
            )

        image = _add_glow(image, accent_rgb,
                          center=(Layout.WIDTH, 120), radius=560, strength=0.22)
        image = _add_glow(image, accent_rgb,
                          center=(0, Layout.HEIGHT - 260), radius=480, strength=0.14)
        return image

    # ---- elements ----

    def _draw_top_bar(self, draw: ImageDraw.ImageDraw, script: ShortScript,
                      accent: str) -> None:
        y = Layout.TOP_BAR_Y

        brand_font = self.fonts.get("latin", Fonts.BRAND)
        textfit.draw_line(draw, (Layout.MARGIN_X, y), self.brand, brand_font,
                          fill=hex_to_rgb(accent), anchor="la")

        # Category pill, right-aligned
        label = script.topic.category_display.upper()
        pill_font = self.fonts.get("latin", Fonts.PILL)
        text_w, _ = textfit.measure(label, pill_font)
        pill_w = text_w + 46
        pill_h = 50
        pill_x = Layout.WIDTH - Layout.MARGIN_X - pill_w
        pill_y = y - 8

        accent_rgb = hex_to_rgb(accent)
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=Layout.PILL_RADIUS,
            fill=(accent_rgb[0] // 7, accent_rgb[1] // 7, accent_rgb[2] // 7),
            outline=accent_rgb, width=2,
        )
        draw.text((pill_x + pill_w // 2, pill_y + pill_h // 2), label,
                  font=pill_font, fill=accent_rgb, anchor="mm")

    def _draw_kicker(self, draw: ImageDraw.ImageDraw, beat: Beat, accent: str) -> None:
        style = KIND_STYLE.get(beat.kind.value, {})
        label = beat.kicker or style.get("label") or ""
        if not label:
            return

        color = style.get("color") or accent
        font = self.fonts.get("latin", Fonts.KICKER)
        center_x = Layout.WIDTH // 2

        text_w, _ = textfit.measure(label, font)
        box_w = text_w + 56
        box_h = 62
        box_x = center_x - box_w // 2
        box_y = Layout.KICKER_Y

        color_rgb = hex_to_rgb(color)
        draw.rounded_rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            radius=16,
            fill=(color_rgb[0] // 6, color_rgb[1] // 6, color_rgb[2] // 6),
            outline=color_rgb, width=3,
        )
        draw.text((center_x, box_y + box_h // 2), label, font=font,
                  fill=color_rgb, anchor="mm")

    def _draw_headline(self, draw: ImageDraw.ImageDraw, beat: Beat,
                       accent: str) -> None:
        if not beat.headline:
            return

        available_height = Layout.HEADLINE_BOTTOM - Layout.HEADLINE_TOP
        font, lines = textfit.fit_block(
            beat.headline, self.fonts,
            max_width=Layout.CONTENT_WIDTH,
            max_height=available_height,
            start_size=Fonts.HEADLINE,
            min_size=Fonts.HEADLINE_MIN,
            line_gap=Layout.HEADLINE_LINE_GAP,
            max_lines=4,
        )

        # Vertically centre the block inside its box so short and long
        # headlines both sit on the same optical line.
        block_h = (len(lines) * textfit.line_height(font)
                   + max(0, len(lines) - 1) * Layout.HEADLINE_LINE_GAP)
        top_y = Layout.HEADLINE_TOP + max(0, (available_height - block_h) // 2)

        bottom = textfit.draw_block(
            draw, lines, font, Layout.WIDTH // 2, top_y,
            fill=hex_to_rgb(Palette.WHITE),
            line_gap=Layout.HEADLINE_LINE_GAP,
            shadow=(0, 0, 0, 200),
            stroke_width=2,
            stroke_fill=hex_to_rgb(Palette.SHADOW),
        )

        draw.rounded_rectangle(
            [Layout.WIDTH // 2 - 110, bottom + 44,
             Layout.WIDTH // 2 + 110, bottom + 52],
            radius=4, fill=hex_to_rgb(accent),
        )

    def _draw_beat_dots(self, draw: ImageDraw.ImageDraw, index: int,
                        count: int, accent: str) -> None:
        """A "how far in am I" cue. Cheap retention signal on a vertical video."""
        if count <= 1:
            return

        gap = 30
        total_w = (count - 1) * gap
        start_x = Layout.WIDTH // 2 - total_w // 2
        accent_rgb = hex_to_rgb(accent)
        dim_rgb = hex_to_rgb(Palette.TEXT_DIM)

        for i in range(count):
            x = start_x + i * gap
            filled = i <= index
            radius = 8 if i == index else 6
            draw.ellipse(
                [x - radius, Layout.DOTS_Y - radius, x + radius, Layout.DOTS_Y + radius],
                fill=accent_rgb if filled else dim_rgb,
            )

    def _draw_follow_pill(self, draw: ImageDraw.ImageDraw, accent: str) -> None:
        label = "FOLLOW FOR DAILY UPSC"
        font = self.fonts.get("latin", Fonts.PILL)
        text_w, _ = textfit.measure(label, font)
        pill_w = text_w + 72
        pill_h = 74
        pill_x = Layout.WIDTH // 2 - pill_w // 2
        # Kept clear of CAPTION_BAND_TOP — the pill and the first caption line
        # must never touch.
        pill_y = Layout.HEADLINE_BOTTOM + 20

        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=37, fill=hex_to_rgb(accent),
        )
        draw.text((Layout.WIDTH // 2, pill_y + pill_h // 2), label, font=font,
                  fill=hex_to_rgb("#0A0E18"), anchor="mm")


# ---- helpers ----

def _add_glow(image: Image.Image, color: Tuple[int, int, int],
              center: Tuple[int, int], radius: int, strength: float) -> Image.Image:
    """
    Screen a soft coloured glow onto the background.

    Drawn small and scaled up: blurring a 1080x1920 surface costs far more than
    blurring a 1/6-scale one, and at this softness the difference is invisible.
    """
    scale = 6
    small = Image.new("RGB", (image.width // scale, image.height // scale), (0, 0, 0))
    draw = ImageDraw.Draw(small)

    cx, cy, r = center[0] // scale, center[1] // scale, radius // scale
    tint = tuple(min(255, int(c * strength)) for c in color)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tint)

    small = small.filter(ImageFilter.GaussianBlur(radius=r // 2))
    glow = small.resize(image.size, Image.BILINEAR)

    from PIL import ImageChops
    return ImageChops.add(image, glow)
