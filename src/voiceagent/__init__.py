"""Outbound voice agent: campaign orchestration, live calls, post-call actions.

`.env` is loaded here rather than in the entrypoints because `storage.py` reads
DATABASE_URL at import time — anything later is too late, and the symptom is a
silently ignored config file rather than an error.
"""

from pathlib import Path

try:
    from dotenv import load_dotenv

    # Repo root, three levels up from src/voiceagent/__init__.py
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # python-dotenv is optional; env vars still work
    pass
