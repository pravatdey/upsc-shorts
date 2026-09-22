"""
Gemini TTS — realistic Hindi narration on the free tier.

Shorts narration is short (roughly 120-140 words), so a Short almost always
fits in a single request. That matters: the free tier allows only a few
requests per minute, and one request per video keeps a 3-video morning run
comfortably inside the limit.
"""

import asyncio
import io
import os
import re
import time
import wave
from pathlib import Path
from typing import List, Optional

try:
    import imageio_ffmpeg
    import pydub
    pydub.AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    pydub.AudioSegment.ffprobe = imageio_ffmpeg.get_ffmpeg_exe().replace("ffmpeg", "ffprobe")
except ImportError:
    pass

from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, normalize

from .base_tts import BaseTTS, TTSResult, TTSVoice, estimate_word_timings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GeminiTTSEngine(BaseTTS):
    """
    Gemini speech synthesis. Free tier, 30 voices, Hindi included.

    Voices that work well for exam content:
      Fenrir  - confident male, the default
      Charon  - deep, authoritative male
      Puck    - energetic male, good for fast Shorts
      Kore    - calm, clear female
      Zephyr  - warm, expressive female
    """

    # Tried in order; the first one the account can reach wins. Keeping a list
    # means a preview model being retired does not break the daily run.
    MODEL_CANDIDATES = [
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
    ]

    DEFAULT_VOICE = "Fenrir"
    MAX_CHARS_PER_REQUEST = 3000

    def __init__(self, api_key: Optional[str] = None, voice_name: str = None,
                 language: str = "hi", models: List[str] = None,
                 speed: float = 0.95):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set (free: https://aistudio.google.com/apikey)")

        self.voice_name = voice_name or self.DEFAULT_VOICE
        self.language = language
        self.models = models or self.MODEL_CANDIDATES
        self.speed = speed
        self._working_model: Optional[str] = None

        from google import genai
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"Gemini TTS ready: voice={self.voice_name}, language={language}")

    # ---- synthesis ----

    async def synthesize(self, text: str, output_path: str,
                         voice: str = None, language: str = None) -> TTSResult:
        voice_name = voice or self.voice_name
        language = language or self.language
        voice_info = TTSVoice(id=f"gemini:{voice_name}", name=voice_name,
                              language=language, provider="gemini")

        cleaned = self.preprocess(text)
        if not cleaned:
            return TTSResult("", 0.0, voice_info, False, error="Empty text")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        chunks = self._split_text(cleaned)
        logger.info(f"Gemini TTS: {len(cleaned)} chars in {len(chunks)} chunk(s)")

        try:
            loop = asyncio.get_event_loop()
            merged: Optional[AudioSegment] = None

            for i, chunk in enumerate(chunks):
                if i > 0:
                    # Free tier is a few requests per minute; pace multi-chunk jobs.
                    await asyncio.sleep(22)
                pcm = await loop.run_in_executor(
                    None, self._synthesize_chunk, chunk, voice_name
                )
                segment = AudioSegment.from_file(
                    io.BytesIO(_pcm_to_wav(pcm)), format="wav"
                )
                merged = segment if merged is None else merged + segment

            merged.export(output_path, format="mp3", bitrate="192k")
            self._postprocess(output_path)

            duration = _duration_of(output_path)
            words = estimate_word_timings(cleaned, duration)
            logger.info(f"Gemini TTS done: {duration:.1f}s, {len(words)} words")
            return TTSResult(str(output_path), duration, voice_info, True, words=words)

        except Exception as e:
            logger.error(f"Gemini TTS failed: {e}")
            return TTSResult("", 0.0, voice_info, False, error=str(e))

    def _synthesize_chunk(self, text: str, voice_name: str) -> bytes:
        """One blocking Gemini call. Returns raw PCM (24 kHz, mono, 16-bit)."""
        from google.genai import types

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        )

        models = [self._working_model] if self._working_model else list(self.models)
        last_error: Optional[Exception] = None

        for model in models:
            backoff = 5
            for attempt in range(1, 5):
                try:
                    response = self.client.models.generate_content(
                        model=model, contents=text, config=config
                    )
                    audio = response.candidates[0].content.parts[0].inline_data.data
                    if audio:
                        self._working_model = model
                        return audio
                    logger.warning(f"{model} returned empty audio (attempt {attempt})")
                except Exception as e:
                    last_error = e
                    message = str(e)
                    logger.warning(f"{model} error (attempt {attempt}): {message}")

                    if "NOT_FOUND" in message or "404" in message:
                        break  # model unavailable to this key — try the next one

                    if "RESOURCE_EXHAUSTED" in message or "429" in message:
                        match = re.search(r"retry in (\d+)", message, re.IGNORECASE)
                        wait = int(match.group(1)) + 5 if match else 50
                        logger.info(f"Quota hit, waiting {wait}s")
                        time.sleep(wait)
                        continue

                time.sleep(backoff)
                backoff *= 2

        raise RuntimeError(f"Gemini TTS exhausted all models: {last_error}")

    # ---- audio shaping ----

    def _postprocess(self, path: str) -> None:
        """
        Tighten the voice for phone speakers.

        Shorts are watched on a phone at low volume in a noisy place, so the
        band-pass plus compression matters more here than on long-form video.
        """
        try:
            audio = AudioSegment.from_file(path)

            if self.speed and abs(self.speed - 1.0) > 0.01:
                original_rate = audio.frame_rate
                audio = audio._spawn(
                    audio.raw_data,
                    overrides={"frame_rate": int(original_rate * self.speed)},
                ).set_frame_rate(original_rate)

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

    def _split_text(self, text: str) -> List[str]:
        if len(text) <= self.MAX_CHARS_PER_REQUEST:
            return [text]

        chunks, current = [], ""
        for sentence in re.split(r"(?<=[.!?।])\s+", text):
            if len(current) + len(sentence) + 1 <= self.MAX_CHARS_PER_REQUEST:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)
        return chunks


# ---- module helpers ----

def _pcm_to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    buffer.seek(0)
    return buffer.read()


def _duration_of(path: str) -> float:
    try:
        return len(AudioSegment.from_file(path)) / 1000.0
    except Exception:
        return 0.0
