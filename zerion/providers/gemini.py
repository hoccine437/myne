# providers/gemini.py
"""Gemini provider. Same request shape as the original api.py, with
retry-on-timeout and clearer error messages for common failure modes."""

import requests
import socket
import time

import config
from providers.base import Provider, ProviderError

_MAX_RETRIES = 2
_RETRY_STATUS = (429, 500, 502, 503, 504)


class GeminiProvider(Provider):
    name = "gemini"

    def is_configured(self) -> bool:
        return bool(config.GEMINI_API_KEY)

    def call(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        if not self.is_configured():
            raise ProviderError("GEMINI_API_KEY is not set")

        try:
            socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=min(timeout, 3)).close()
        except OSError as exc:
            raise ProviderError(f"Gemini network unavailable: {exc}")
        headers = {"Content-Type": "application/json"}
        params = {"key": config.GEMINI_API_KEY}
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
        }

        last_error = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = requests.post(
                    config.GEMINI_URL, headers=headers, params=params, json=payload, timeout=timeout,
                )
            except requests.exceptions.Timeout:
                last_error = ProviderError(f"Gemini request timed out after {timeout}s")
                continue
            except requests.exceptions.RequestException as e:
                last_error = ProviderError(f"Gemini network error: {e}")
                continue

            if response.status_code == 401 or response.status_code == 403:
                raise ProviderError("Gemini API key is invalid or unauthorized")

            if response.status_code in _RETRY_STATUS:
                if response.status_code == 429:
                    last_error = ProviderError("Gemini rate limit/quota exceeded -- try again shortly")
                else:
                    last_error = ProviderError(
                        f"Gemini API error {response.status_code}: {response.text[:200]}"
                    )
                if attempt < _MAX_RETRIES:
                    # Respect Retry-After when the server sends one; otherwise
                    # back off a little longer each attempt (0.5s, 1.5s, ...).
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else 0.5 + attempt
                    except ValueError:
                        delay = 0.5 + attempt
                    time.sleep(min(delay, 5))
                continue

            if response.status_code != 200:
                raise ProviderError(f"Gemini API error {response.status_code}: {response.text[:200]}")

            try:
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (ValueError, KeyError, IndexError) as e:
                raise ProviderError(f"Gemini returned an unexpected response shape: {e}")

        raise last_error or ProviderError("Gemini request failed for an unknown reason")
