"""
Edge TTS — the fallback voice.

Less expressive than Gemini, but it has no quota, never fails on a busy
morning, and returns *real* word boundaries rather than estimates, so captions
generated from it are frame-accurate.
"""

from pathlib import Path
from typing import List

try:
    import imageio_ffmpeg
    import pydub
    pydub.AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    pydub.AudioSegment.ffprobe = imageio_ffmpeg.get_ffmpeg_exe().replace("ffmpeg", "ffprobe")
except ImportError:
    pass

import edge_tts
from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

from .base_tts import BaseTTS, TTSResult, TTSVoice, WordTiming
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EdgeTTSEngine(BaseTTS):
    DEFAULT_VOICES = {
        "hi": "hi-IN-MadhurNeural",
        "en": "en-IN-PrabhatNeural",
    }

    def __init__(self, voice: str = None, language: str = "hi",
                 rate: str = "+8%", pitch: str = "+0Hz", volume: str = "+0%"):
        self.language = language
        self.voice = voice or self.DEFAULT_VOICES.get(language, self.DEFAULT_VOICES["hi"])
        # Shorts reward a slightly quicker read than long-form lessons do.
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        logger.info(f"Edge TTS ready: voice={self.voice}, rate={rate}")

    async def synthesize(self, text: str, output_path: str,
                         voice: str = None, language: str = None) -> TTSResult:
        voice_name = voice or self.voice
        voice_info = TTSVoice(id=voice_name, name=voice_name,
                              language=language or self.language, provider="edge")

        cleaned = self.preprocess(text)
        if not cleaned:
            return TTSResult("", 0.0, voice_info, False, error="Empty text")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            communicate = edge_tts.Communicate(
                text=cleaned, voice=voice_name,
                rate=self.rate, pitch=self.pitch, volume=self.volume,
            )

            audio_bytes = b""
            words: List[WordTiming] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
                elif chunk["type"] == "WordBoundary":
                    # edge-tts reports in 100-nanosecond ticks
                    start = chunk["offset"] / 10_000_000
                    end = start + chunk["duration"] / 10_000_000
                    words.append(WordTiming(text=chunk["text"], start=start, end=end))

            if not audio_bytes:
                return TTSResult("", 0.0, voice_info, False, error="Edge TTS returned no audio")

            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            self._postprocess(output_path)
            duration = _duration_of(output_path)

            logger.info(f"Edge TTS done: {duration:.1f}s, {len(words)} word boundaries")
            return TTSResult(str(output_path), duration, voice_info, True, words=words)

        except Exception as e:
            logger.error(f"Edge TTS failed: {e}")
            return TTSResult("", 0.0, voice_info, False, error=str(e))

    @staticmethod
    def _postprocess(path: str) -> None:
        try:
            audio = AudioSegment.from_file(path)
            audio = audio.high_pass_filter(90)
            audio = audio.low_pass_filter(12000)
            try:
                audio = compress_dynamic_range(audio, threshold=-16.0, ratio=3.0,
                                               attack=5.0, release=80.0)
            except Exception:
                pass
            audio = normalize(audio, headroom=1.0)
            audio.export(path, format="mp3", bitrate="192k")
        except Exception as e:
            logger.warning(f"Audio post-processing skipped: {e}")


def _duration_of(path: str) -> float:
    try:
        return len(AudioSegment.from_file(path)) / 1000.0
    except Exception:
        return 0.0
