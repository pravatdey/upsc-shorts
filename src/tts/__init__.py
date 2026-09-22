"""
Text-to-speech: Gemini (realistic Hindi) with Edge TTS fallback.

Only the data types are re-exported here. The engines are deliberately *not*
imported at package level: `WordTiming` is needed by the video code, and
pulling in edge-tts and the Google SDK just to name a dataclass would make
rendering depend on network libraries it never uses.

Import the manager directly where it is needed:

    from src.tts.tts_manager import TTSManager
"""

from .base_tts import TTSResult, TTSVoice, WordTiming

__all__ = ["TTSResult", "TTSVoice", "WordTiming"]
