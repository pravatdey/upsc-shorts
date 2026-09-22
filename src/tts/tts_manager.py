"""
TTS Manager — Gemini first, Edge TTS as the safety net.

A failed narration means no video at all, so this layer always keeps a working
fallback constructed and ready rather than discovering the problem mid-run.
"""

import os
from pathlib import Path
from typing import Any, Dict

from .base_tts import TTSResult
from .edge_tts_engine import EdgeTTSEngine
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TTSManager:
    def __init__(self, config: Dict[str, Any]):
        tts_config = config.get("tts", {})
        self.provider = tts_config.get("provider", "gemini")
        language = tts_config.get("language", "hi")

        edge_config = tts_config.get("edge", {})
        self.edge = EdgeTTSEngine(
            voice=edge_config.get("voice"),
            language=language,
            rate=edge_config.get("rate", "+8%"),
            pitch=edge_config.get("pitch", "+0Hz"),
        )

        self.gemini = None
        if self.provider == "gemini":
            try:
                from .gemini_tts_engine import GeminiTTSEngine
                gemini_config = tts_config.get("gemini", {})
                self.gemini = GeminiTTSEngine(
                    api_key=os.getenv("GEMINI_API_KEY"),
                    voice_name=gemini_config.get("voice_name", "Fenrir"),
                    language=language,
                    models=gemini_config.get("models"),
                    speed=gemini_config.get("speed", 0.95),
                )
            except Exception as e:
                logger.warning(f"Gemini TTS unavailable ({e}); using Edge TTS only")

        logger.info(f"TTSManager ready: primary={'gemini' if self.gemini else 'edge'}")

    async def narrate(self, text: str, output_path: str) -> TTSResult:
        """Synthesize narration, falling back to Edge TTS if Gemini fails."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if self.gemini is not None:
            result = await self.gemini.synthesize(text, output_path)
            if result.success and result.duration > 0:
                return result
            logger.warning(f"Gemini TTS unusable ({result.error}); falling back to Edge TTS")

        return await self.edge.synthesize(text, output_path)
