"""War Room Voice

Provides spoken audio alerts and status reads for POLAR.
Supports two engines:
  - pyttsx3: Local TTS, zero API cost, works offline
  - elevenlabs: High-quality cloud TTS via ElevenLabs API

Set WAR_ROOM_VOICE_ENGINE=pyttsx3|elevenlabs in .env
"""

import logging
import os
import threading
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

ENGINE = os.getenv("WAR_ROOM_VOICE_ENGINE", "pyttsx3").lower()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ------------------------------------------------------------------
# Engine: pyttsx3 (local)
# ------------------------------------------------------------------

def _speak_local(text: str, rate: int = 175) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    voices = engine.getProperty("voices")
    # Prefer a deeper voice for War Room feel
    for v in voices:
        if "david" in v.name.lower() or "male" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.say(text)
    engine.runAndWait()
    engine.stop()


# ------------------------------------------------------------------
# Engine: ElevenLabs (cloud)
# ------------------------------------------------------------------

def _speak_elevenlabs(text: str) -> None:
    try:
        from elevenlabs import generate, play, set_api_key
        set_api_key(ELEVENLABS_API_KEY)
        audio = generate(text=text, voice=ELEVENLABS_VOICE_ID, model="eleven_monolingual_v1")
        play(audio)
    except Exception as e:
        logger.error(f"ElevenLabs TTS failed: {e}. Falling back to local.")
        _speak_local(text)


# ------------------------------------------------------------------
# Public interface
# ------------------------------------------------------------------

def speak(text: str, blocking: bool = False) -> None:
    """
    Speak text using the configured engine.

    Args:
        text: The text to speak.
        blocking: If True, block until speech completes.
                  If False, speak in a background thread.
    """
    def _run():
        with _lock:
            if ENGINE == "elevenlabs" and ELEVENLABS_API_KEY:
                _speak_elevenlabs(text)
            else:
                _speak_local(text)

    if blocking:
        _run()
    else:
        t = threading.Thread(target=_run, daemon=True)
        t.start()


class WarRoomVoice:
    """Structured voice alerts for POLAR War Room mode."""

    def alert(self, message: str) -> None:
        """High-priority alert. Blocking."""
        speak(f"Alert. {message}", blocking=True)

    def briefing(self, agent: str, summary: str) -> None:
        """Agent briefing read-back."""
        speak(f"{agent} agent reporting. {summary}", blocking=False)

    def status(self, online_agents: list[str]) -> None:
        """System status read."""
        agent_list = ", ".join(online_agents) if online_agents else "none"
        speak(f"POLAR status. Active agents: {agent_list}.", blocking=False)

    def task_complete(self, agent: str, task: str) -> None:
        """Confirmation that a task was completed."""
        speak(f"{agent} agent has completed task: {task}.", blocking=False)

    def error(self, agent: str, error: str) -> None:
        """Error notification."""
        speak(f"Warning. {agent} agent encountered an error. {error}", blocking=True)

    def startup(self) -> None:
        """POLAR startup announcement."""
        speak("POLAR online. All systems nominal. Awaiting instruction.", blocking=False)

    def shutdown(self) -> None:
        """POLAR shutdown announcement."""
        speak("POLAR shutting down. Saving state to Hive Mind.", blocking=True)
