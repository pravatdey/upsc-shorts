"""
LLM Client — Groq (primary) with automatic Gemini fallback.

Both providers have generous free tiers. Groq is fast and reliable for JSON;
Gemini takes over when Groq is rate-limited or its key is missing, so a daily
run never dies just because one provider had a bad minute.
"""

import os
import time
from abc import ABC, abstractmethod
from typing import List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BaseLLMClient(ABC):
    name = "base"

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = None,
                 max_tokens: int = 4000, temperature: float = 0.8) -> str:
        ...


class GroqClient(BaseLLMClient):
    name = "groq"

    def __init__(self, api_key: str = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set (free key: https://console.groq.com/keys)")

        from groq import Groq
        self.client = Groq(api_key=self.api_key)
        logger.info(f"Groq client ready: {model}")

    def generate(self, prompt: str, system_prompt: str = None,
                 max_tokens: int = 4000, temperature: float = 0.8) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return (response.choices[0].message.content or "").strip()


class GeminiClient(BaseLLMClient):
    name = "gemini"

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set (free key: https://aistudio.google.com/apikey)")

        from google import genai
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"Gemini client ready: {model}")

    def generate(self, prompt: str, system_prompt: str = None,
                 max_tokens: int = 4000, temperature: float = 0.8) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )
        if system_prompt:
            config.system_instruction = system_prompt

        response = self.client.models.generate_content(
            model=self.model, contents=prompt, config=config
        )
        return (response.text or "").strip()


class LLMClient:
    """
    Tries providers in order until one returns text.

    Retries within a provider handle transient 429/5xx; moving to the next
    provider handles a hard outage or an exhausted daily quota.
    """

    def __init__(self, provider: str = "groq",
                 groq_model: str = "llama-3.3-70b-versatile",
                 gemini_model: str = "gemini-2.5-flash",
                 max_retries: int = 3):
        self.max_retries = max_retries
        self.clients: List[BaseLLMClient] = []

        order = ["groq", "gemini"] if provider == "groq" else ["gemini", "groq"]
        builders = {
            "groq": lambda: GroqClient(model=groq_model),
            "gemini": lambda: GeminiClient(model=gemini_model),
        }

        for key in order:
            try:
                self.clients.append(builders[key]())
            except Exception as e:
                logger.warning(f"{key} unavailable: {e}")

        if not self.clients:
            raise RuntimeError(
                "No LLM provider available. Set GROQ_API_KEY and/or GEMINI_API_KEY."
            )

        logger.info(f"LLM chain: {' -> '.join(c.name for c in self.clients)}")

    def generate(self, prompt: str, system_prompt: str = None,
                 max_tokens: int = 4000, temperature: float = 0.8) -> str:
        last_error: Optional[Exception] = None

        for client in self.clients:
            backoff = 4
            for attempt in range(1, self.max_retries + 1):
                try:
                    text = client.generate(
                        prompt=prompt, system_prompt=system_prompt,
                        max_tokens=max_tokens, temperature=temperature,
                    )
                    if text:
                        return text
                    logger.warning(f"{client.name} returned empty text (attempt {attempt})")
                except Exception as e:
                    last_error = e
                    logger.warning(f"{client.name} error (attempt {attempt}): {e}")
                    if not _is_retriable(e):
                        break
                if attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
            logger.warning(f"{client.name} exhausted, trying next provider")

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


def _is_retriable(error: Exception) -> bool:
    text = str(error).lower()
    markers = ("429", "rate", "quota", "resource_exhausted", "timeout",
               "500", "502", "503", "504", "overloaded", "unavailable")
    return any(m in text for m in markers)
