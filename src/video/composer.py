"""
Short Composer — assembles the finished 1080x1920 video.

Unlike a slideshow built from stacked MoviePy clips, this renders every frame
from a single `make_frame`. That matters at this resolution: a per-word caption
overlay expressed as clips would mean a hundred-plus full-frame RGBA layers
held in memory at once, while here the only things retained are the handful of
beat cards and a tiny cache of caption bands.
"""

import bisect
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):          # Pillow 10 removed the alias
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import numpy as np
from moviepy.editor import AudioFileClip, CompositeAudioClip, VideoClip
from PIL import Image, ImageDraw

from .captions import CaptionBuilder, CaptionRenderer, align_beats
from .card_renderer import CardRenderer
from .fonts import FontBook
from .theme import Layout, Palette, hex_to_rgb
from src.content.models import ShortScript
from src.tts.base_tts import WordTiming
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ShortComposer:
    def __init__(self, config: Dict[str, Any], fonts: FontBook = None):
        video_config = config.get("video", {})
        self.fps = video_config.get("fps", 30)
        self.codec = video_config.get("codec", "libx264")
        self.bitrate = video_config.get("bitrate", "8000k")
        self.preset = video_config.get("preset", "medium")
        self.threads = video_config.get("threads", 4)
        self.zoom = float(video_config.get("zoom", 1.06))

        music_config = config.get("music", {})
        self.music_enabled = music_config.get("enabled", False)
        self.music_file = music_config.get("file", "")
        self.music_volume = float(music_config.get("volume", 0.06))

        self.fonts = fonts or FontBook()
        self.cards = CardRenderer(
            brand=config.get("channel", {}).get("brand", "UPSC SHORTS"),
            fonts=self.fonts,
        )

    def compose(self, script: ShortScript, audio_path: str,
                words: List[WordTiming], audio_duration: float,
                output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        accent = Palette.accent(script.topic.category)
        accent_rgb = hex_to_rgb(accent)

        beats = script.beats
        spans = align_beats(script, words, audio_duration)

        logger.info(f"Rendering {len(beats)} beat cards")
        cards = [
            np_ready(self.cards.render(script, beat, i, len(beats)))
            for i, beat in enumerate(beats)
        ]

        builder = CaptionBuilder(self.fonts)
        windows = builder.build(words)
        captions = CaptionRenderer(self.fonts, accent)
        captions.prepare(windows)
        window_starts = [w.start for w in windows]

        beat_starts = [s for s, _ in spans]
        band_y = Layout.CAPTION_BAND_TOP

        def make_frame(t: float) -> np.ndarray:
            # Which beat card is on screen
            beat_index = bisect.bisect_right(beat_starts, t) - 1
            beat_index = max(0, min(len(cards) - 1, beat_index))
            card = cards[beat_index]

            frame = self._apply_zoom(card, t, spans[beat_index], beat_index)
            draw = ImageDraw.Draw(frame)

            # Overall progress bar — a visible "almost done" cue lifts completion rate
            progress = 0.0 if audio_duration <= 0 else min(1.0, t / audio_duration)
            draw.rectangle(
                [0, 0, Layout.WIDTH, Layout.PROGRESS_BAR_HEIGHT],
                fill=(26, 32, 48),
            )
            if progress > 0:
                draw.rectangle(
                    [0, 0, int(Layout.WIDTH * progress), Layout.PROGRESS_BAR_HEIGHT],
                    fill=accent_rgb,
                )

            if windows:
                index = max(0, bisect.bisect_right(window_starts, t) - 1)
                band = captions.band(index, windows[index].active_index(t))
                if band is not None:
                    frame.paste(band, (0, band_y), band)

            return np.asarray(frame)

        logger.info(f"Encoding {audio_duration:.1f}s at {self.fps}fps -> {output_path}")

        video = VideoClip(make_frame, duration=audio_duration)
        video.fps = self.fps
        video = video.set_audio(self._build_audio(audio_path, audio_duration))

        video.write_videofile(
            output_path,
            fps=self.fps,
            codec=self.codec,
            bitrate=self.bitrate,
            preset=self.preset,
            audio_codec="aac",
            audio_bitrate="192k",
            threads=self.threads,
            logger=None,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        )
        video.close()

        logger.info(f"Video written: {output_path}")
        return output_path

    # ---- frame helpers ----

    def _apply_zoom(self, card: Image.Image, t: float,
                    span: Tuple[float, float], beat_index: int) -> Image.Image:
        """
        Slow Ken Burns move across each beat.

        A completely static frame reads as a screenshot and gets swiped past;
        continuous motion is what makes a generated Short feel like video.
        Direction alternates per beat so consecutive cards do not pulse in sync.
        """
        start, end = span
        duration = max(0.001, end - start)
        progress = min(1.0, max(0.0, (t - start) / duration))

        if beat_index % 2 == 0:
            scale = 1.0 + (self.zoom - 1.0) * progress          # push in
        else:
            scale = self.zoom - (self.zoom - 1.0) * progress    # pull out

        if scale <= 1.001:
            return card.copy()

        crop_w = int(Layout.WIDTH / scale)
        crop_h = int(Layout.HEIGHT / scale)
        left = (Layout.WIDTH - crop_w) // 2
        top = (Layout.HEIGHT - crop_h) // 2

        cropped = card.crop((left, top, left + crop_w, top + crop_h))
        return cropped.resize((Layout.WIDTH, Layout.HEIGHT), Image.BILINEAR)

    def _build_audio(self, audio_path: str, duration: float):
        narration = AudioFileClip(audio_path)

        # Never hand MoviePy an audio track longer than the video: the tail gets
        # written as a final frame of silence with a frozen image.
        if narration.duration > duration:
            narration = narration.subclip(0, duration)

        tracks = [narration]

        if self.music_enabled and self.music_file and Path(self.music_file).exists():
            try:
                music = AudioFileClip(self.music_file)
                if music.duration < duration:
                    music = music.loop(n=int(duration / music.duration) + 1)
                music = music.subclip(0, duration).volumex(self.music_volume)
                tracks.append(music)
            except Exception as e:
                logger.warning(f"Background music skipped: {e}")

        return CompositeAudioClip(tracks) if len(tracks) > 1 else narration


def np_ready(image: Image.Image) -> Image.Image:
    """Cards are composited onto, so they must be RGB and mutable."""
    return image.convert("RGB")


def fit_audio_duration(audio_path: str, words: List[WordTiming],
                       duration: float, max_duration: float
                       ) -> Tuple[float, List[WordTiming]]:
    """
    Speed the narration up just enough to stay inside the Shorts ceiling.

    Crossing 60 seconds takes a video off the Shorts shelf entirely, which is a
    far worse outcome than a 6% faster read. ffmpeg's `atempo` preserves pitch,
    so the voice does not turn chipmunky. Word timings are rescaled by the same
    factor so captions stay in sync.
    """
    if duration <= max_duration or duration <= 0:
        return duration, words

    tempo = duration / max_duration
    if tempo > 1.25:
        logger.warning(
            f"Narration is {duration:.1f}s against a {max_duration:.0f}s limit. "
            f"Capping the speed-up at 1.25x; the Short will still run long. "
            f"Lower script.target_seconds in config/settings.yaml."
        )
        tempo = 1.25

    logger.info(f"Narration {duration:.1f}s exceeds {max_duration:.0f}s; "
                f"applying atempo={tempo:.3f}")

    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"

    source = Path(audio_path)
    temp = source.with_name(source.stem + "_fit.mp3")
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-filter:a", f"atempo={tempo:.4f}",
         "-b:a", "192k", str(temp)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(f"atempo failed, keeping original audio: {result.stderr[-400:]}")
        return duration, words

    temp.replace(source)

    # Measure rather than assume duration/tempo. ffmpeg's atempo lands close but
    # not exactly on the arithmetic result, and the composer uses this number as
    # the video's length — if it overruns the real audio, the final frames carry
    # silence; if it undershoots, the narration is cut off mid-word.
    new_duration = _measure_duration(str(source)) or (duration / tempo)
    actual_tempo = duration / new_duration if new_duration > 0 else tempo

    rescaled = [
        WordTiming(text=w.text, start=w.start / actual_tempo,
                   end=w.end / actual_tempo)
        for w in words
    ]
    logger.info(f"Narration now {new_duration:.1f}s")
    return new_duration, rescaled


def _measure_duration(path: str) -> float:
    clip = None
    try:
        clip = AudioFileClip(path)
        return float(clip.duration)
    except Exception as e:
        logger.warning(f"Could not measure audio duration: {e}")
        return 0.0
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass
