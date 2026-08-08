# providers/base.py
"""
Abstract interface every LLM provider must implement. The rest of the
project (llm.py, and everything above it) only ever talks to
providers.router.call_llm() -- never to a specific provider module
directly -- so adding a new provider or swapping the active one never
requires touching any other file.
"""

from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Raised by a provider on any failure (missing key, network error,
    bad response, rate limit, timeout). Always carries a human-readable
    message; callers never need to inspect a raw exception type from the
    underlying HTTP library."""
    pass


class Provider(ABC):
    #: Short identifier used in config (e.g. "gemini", "gpt", "deepseek").
    name: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """True if this provider has what it needs (API key, etc.) to be
        called right now. Must never raise."""
        raise NotImplementedError

    @abstractmethod
    def call(self, system_prompt: str, user_prompt: str, timeout: int,
             image_b64: str | None = None, image_mime: str | None = None) -> str:
        """Send one request and return the response text. Raises
        ProviderError on any failure -- never returns None, never raises
        a raw requests/network exception to the caller.

        When supplied, the image is attached as an inline image part using
        the provider's multimodal convention (Gemini: inline_data). Providers
        that don't support multimodal input must raise a clear ProviderError
        rather than silently dropping the image — caller then falls back
        text-only."""
