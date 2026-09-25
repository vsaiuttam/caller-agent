"""Sealing an MCP server's URL and headers at rest.

They are credentials — an API key in a header, or a token in the URL — so
they are encrypted in the database and never sent back out: once entered,
the console can replace them but not read them.

Fernet (AES-128-CBC with HMAC-SHA256, from `cryptography`), keyed by a
SHA-256 of `SECRETS_KEY`, falling back to `AUTH_SECRET`. With neither set the
data is stored readable, prefixed `plain:`, and `sealing_enabled()` says so,
so the console can ask for a key rather than pretend. Rows stored plain stay
readable after a key is set; they are sealed when next saved.

Changing or removing the key makes existing rows unreadable. That surfaces
as `SecretsUnavailable`, which the servers show as an error asking for the
URL and credentials again — the only fix there is, since nothing can recover
them.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PLAIN_PREFIX = "plain:"
REENTER_MESSAGE = "Re-enter this server's URL and credentials."


class SecretsUnavailable(Exception):
    """Sealed data that the current key cannot open."""


def _key_material() -> str:
    return os.getenv("SECRETS_KEY", "").strip() or os.getenv("AUTH_SECRET", "").strip()


def sealing_enabled() -> bool:
    """Whether new secrets are encrypted, i.e. a key is configured."""
    return bool(_key_material())


def _fernet() -> Fernet | None:
    material = _key_material()
    if not material:
        return None
    # Hashed rather than used directly, so any passphrase makes a valid key.
    digest = hashlib.sha256(b"samvaad-mcp-secrets:" + material.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    fernet = _fernet()
    if fernet is None:
        return PLAIN_PREFIX + base64.b64encode(raw).decode()
    return fernet.encrypt(raw).decode()


def unseal(text: str) -> dict[str, Any]:
    """The data `seal` was given. Raises `SecretsUnavailable` if it can't be read."""
    raw = _decode_plain(text) if text.startswith(PLAIN_PREFIX) else _decrypt(text)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SecretsUnavailable("These secrets are not in a readable form.") from exc
    if not isinstance(data, dict):
        raise SecretsUnavailable("These secrets are not in a readable form.")
    return data


def _decode_plain(text: str) -> bytes:
    try:
        return base64.b64decode(text[len(PLAIN_PREFIX):], validate=True)
    except binascii.Error as exc:
        raise SecretsUnavailable("These secrets are not in a readable form.") from exc


def _decrypt(text: str) -> bytes:
    fernet = _fernet()
    if fernet is None:
        raise SecretsUnavailable("These secrets were sealed with a key that is no longer set.")
    try:
        return fernet.decrypt(text.encode())
    except InvalidToken as exc:
        raise SecretsUnavailable("These secrets cannot be opened with the current key.") from exc
