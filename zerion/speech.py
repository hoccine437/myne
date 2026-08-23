# speech.py
"""
Optional speech output, powered by Gemini's native text-to-speech.

Speech is a pure convenience layer on top of the terminal — nothing here
can crash the main loop. If the API key is missing, the network is down,
generation fails, or no audio player is available, this module silently
falls back to printing the text (which main.py already does) and moves on.

Pipeline:
    text -> Gemini generateContent (responseModalities=["AUDIO"])
         -> base64 PCM (16-bit, 24kHz, mono)
         -> wrapped in a WAV header (stdlib `wave`, no extra dependency)
         -> written to a temp file
         -> played with an available player (Termux or desktop)
         -> temp file deleted

Speech input (microphone) is intentionally not part of this module —
Mark-X Lite is keyboard-first; this file covers voice OUTPUT only.
"""

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import wave

import requests

import config

# ---------------------------------------------------------------------------
# Availability detection (never raises)
# ---------------------------------------------------------------------------

_player_cmd = None  # resolved lazily, cached after first successful detect


def _detect_player():
    """Find an available audio player. Termux's own player is preferred on
    Android since it needs no extra packages beyond termux-api. Falls back
    to common desktop/Linux players."""
    global _player_cmd
    if _player_cmd is not None:
        return _player_cmd

    for candidate in ("termux-media-player", "mpv", "ffplay", "aplay", "paplay"):
        if shutil.which(candidate):
            _player_cmd = candidate
            return _player_cmd

    _player_cmd = ""
    return _player_cmd


def _is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


def speech_status() -> str:
    """Return the single public startup speech state."""
    if not config.VOICE_ENABLED or config.VOICE_PROVIDER != "gemini":
        return "Speech: disabled."
    if not config.get_gemini_api_key() or not config.gemini_tts_supported() or not _detect_player():
        return "Speech: disabled."
    return "Speech: Gemini voice ready."


# ---------------------------------------------------------------------------
# Text cleanup before sending to TTS
# ---------------------------------------------------------------------------

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]+",
    flags=re.UNICODE,
)


def _prepare_text(text: str) -> str:
    """Strip emojis (Gemini TTS reads them aloud literally, e.g. "waving
    hand emoji") and collapse whitespace. Leaves punctuation intact, since
    punctuation is what gives Gemini TTS natural pacing and intonation."""
    text = _EMOJI_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(text: str) -> str:
    cache_dir = os.path.join(tempfile.gettempdir(), "mark-x-lite-tts-cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha256(
        f"{text}|{config.VOICE_NAME}|{config.VOICE_LANGUAGE}".encode("utf-8")
    ).hexdigest()
    return os.path.join(cache_dir, f"{key}.wav")


# ---------------------------------------------------------------------------
# Gemini TTS call
# ---------------------------------------------------------------------------

def _gemini_tts_url() -> str:
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_TTS_MODEL}:generateContent"
    )


def _pcm_to_wav(pcm_bytes: bytes, path: str, rate: int = 24000,
                 channels: int = 1, sample_width: int = 2) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)


def _generate_audio(text: str) -> str:
    """Call Gemini TTS and write a playable WAV file. Returns the file
    path, or "" on any failure (missing key, timeout, bad response, ...).
    Retries once on transient network errors."""
    # This is deliberately the same key accessor used by the text provider.
    # Voice has a different Gemini model/response modality, not a different
    # credential.
    api_key = config.get_gemini_api_key()
    if not api_key:
        return ""
    if not config.gemini_tts_supported():
        print(f"(Gemini TTS disabled: configured speech model {config.GEMINI_TTS_MODEL!r} is not explicitly TTS-capable)")
        return ""

    headers = {"Content-Type": "application/json"}
    params = {"key": api_key}

    # Natural-language style instruction, as Gemini TTS is "controllable" —
    # it reads style/pace cues from the prompt itself, not separate params.
    #
    # IMPORTANT: gemini-2.5-flash-preview-tts will sometimes try to *answer*
    # the text instead of just vocalizing it (especially when the text ends
    # in a question, or the style prefix reads like an instruction to follow
    # rather than a delivery note). When it does that, the API rejects the
    # response with a 400 "Model tried to generate text, but it should only
    # be used for TTS" error. Framing the prompt as an explicit read-aloud
    # transcript, with the target text fenced off and quoted, reliably stops
    # the model from treating it as a conversational turn.
    pace_note = ""
    if config.VOICE_SPEED == "slow":
        pace_note = " Speak slowly and clearly."
    elif config.VOICE_SPEED == "fast":
        pace_note = " Speak at a brisk pace."

    escaped_text = text.replace('"', "'")
    speak_instruction = (
        "You are a text-to-speech engine. Read the following transcript aloud "
        "exactly as written, word for word. Do not answer it, translate it, "
        "add anything to it, or treat it as a request or question directed at "
        f"you — only vocalize it.{pace_note}\n\nTranscript: \"{escaped_text}\""
    )

    payload = {
        "contents": [{"parts": [{"text": speak_instruction}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": config.VOICE_NAME}
                }
            },
        },
    }

    last_error = None
    for attempt in range(2):  # one retry on transient failure
        try:
            response = requests.post(
                _gemini_tts_url(),
                headers=headers,
                params=params,
                json=payload,
                timeout=config.REQUEST_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            last_error = "timeout"
            continue
        except requests.exceptions.RequestException as e:
            last_error = f"network error: {e}"
            continue

        if response.status_code == 401 or response.status_code == 403:
            print(f"(speech output disabled: invalid Gemini API key)")
            return ""
        if response.status_code == 429:
            print(f"(speech output skipped: Gemini quota exceeded)")
            return ""
        if response.status_code != 200:
            last_error = f"API error {response.status_code}: {response.text[:200]}"
            continue

        try:
            data = response.json()
            part = data["candidates"][0]["content"]["parts"][0]
            b64_audio = part["inlineData"]["data"]
        except (KeyError, IndexError, ValueError):
            last_error = "empty or unexpected response shape"
            continue

        if not b64_audio:
            last_error = "empty audio payload"
            continue

        try:
            pcm_bytes = base64.b64decode(b64_audio)
            out_path = _cache_path(text) if config.VOICE_CACHE else os.path.join(
                tempfile.mkdtemp(prefix="mark-x-tts-"), "reply.wav"
            )
            _pcm_to_wav(pcm_bytes, out_path)
            return out_path
        except Exception as e:
            last_error = f"invalid audio data: {e}"
            continue

    print(f"(speech generation failed: {last_error})")
    return ""


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def _play(path: str) -> bool:
    player = _detect_player()
    if not player:
        return False

    try:
        if player == "termux-media-player":
            subprocess.run([player, "play", path], timeout=60,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # termux-media-player plays asynchronously; give it a moment,
            # then stop so we don't leak a background player process.
            _wait_termux_playback(path)
        elif player == "mpv":
            subprocess.run([player, "--no-video", "--really-quiet", path],
                            timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif player == "ffplay":
            subprocess.run([player, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                            timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:  # aplay, paplay
            subprocess.run([player, path], timeout=60,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"(speech playback failed: {e})")
        return False


def _wait_termux_playback(path: str) -> None:
    """termux-media-player's `play` returns immediately; estimate playback
    duration from the WAV file itself and wait that long so we don't delete
    the file (or move on) before Android finishes playing it."""
    import time
    try:
        with wave.open(path, "rb") as wf:
            duration = wf.getnframes() / float(wf.getframerate())
        time.sleep(min(duration + 0.3, 30))
    except Exception:
        time.sleep(2)
    finally:
        try:
            subprocess.run(["termux-media-player", "stop"], timeout=5,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Speak final response text with Gemini TTS; text mode remains available on failure."""
    if not text or not config.VOICE_ENABLED:
        return

    if not config.get_gemini_api_key():
        print("(Gemini speech disabled: GEMINI_API_KEY is not set)")
        return
    if not config.gemini_tts_supported():
        print(f"(Gemini speech disabled: {config.GEMINI_TTS_MODEL!r} is not TTS-capable)")
        return
    if not _detect_player():
        print("(Gemini speech disabled: no audio player found)")
        return

    clean_text = _prepare_text(text)
    if not clean_text:
        return

    cache_hit = config.VOICE_CACHE and os.path.exists(_cache_path(clean_text))
    audio_path = _cache_path(clean_text) if cache_hit else _generate_audio(clean_text)

    if not audio_path:
        print("(Gemini speech unavailable: generation, network, quota, or API failure)")
        return

    try:
        _play(audio_path)
    finally:
        # Never leave orphan files: only delete non-cached (temp-dir) audio.
        if not config.VOICE_CACHE:
            try:
                shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Speech input (kept as a no-op stub for interface parity with main.py /
# terminal.py, which may call listen()). Mark-X Lite is keyboard-first;
# this module's scope is voice OUTPUT only, per design.
# ---------------------------------------------------------------------------

def listen() -> str:
    return ""
