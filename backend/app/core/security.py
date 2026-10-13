from __future__ import annotations

import base64
import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from .errors import ConfigurationError

_SECRET_NAMES = (
    r"password|passwd|clientnonce|servernonce|newclientnonce|"  # noqa: S105
    r"oldservernonce|newservernonce|signature|auth(?:orization)?|token"  # noqa: S105
)
_JSON_SECRET_STRING = re.compile(
    rf"(?i)([\"']?(?:{_SECRET_NAMES})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)"
)
_ASSIGNMENT_SECRET = re.compile(
    rf"(?i)\b({_SECRET_NAMES})"
    r"\b(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^,;\s}\]]+)"
)
_AUTH_HEADER = re.compile(r"(?i)\bUser=[^;\s]+;Signature=[^\s,}]+")
_URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@")


def sanitize_text(value: object, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _JSON_SECRET_STRING.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]{match.group(2)}",
        text,
    )
    text = _AUTH_HEADER.sub("User=[REDACTED];Signature=[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    text = _ASSIGNMENT_SECRET.sub(r"\1\2[REDACTED]", text)
    return text[:1000]


def public_endpoint(value: str | None) -> str | None:
    """Keep a displayable endpoint without URL credentials or opaque query values."""

    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.hostname:
            return urlunsplit(
                (parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")
            )
    except ValueError:
        pass
    # Also handle malformed and scheme-less addresses supplied by older modules.
    return sanitize_text(value.rsplit("@", 1)[-1].split("?", 1)[0].split("#", 1)[0])


def _normalize_fernet_key(value: str) -> bytes:
    raw = value.strip().encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(raw)
    except Exception:
        decoded = b""
    if len(decoded) == 32:
        return raw
    # Environment secret managers often provide passphrases rather than Fernet keys.
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


class CredentialCipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls, data_dir: Path, configured_key: str | None) -> CredentialCipher:
        if configured_key:
            return cls(_normalize_fernet_key(configured_key))
        key_path = data_dir / ".connectmap-key"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            key = key_path.read_bytes().strip()
        except FileNotFoundError:
            key = Fernet.generate_key()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                descriptor = os.open(key_path, flags, 0o600)
            except FileExistsError:
                key = key_path.read_bytes().strip()
            else:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(key + b"\n")
                try:
                    key_path.chmod(0o600)
                except OSError:
                    pass
        try:
            return cls(key)
        except (ValueError, TypeError) as exc:
            raise ConfigurationError("The ConnectMap encryption key is invalid.") from exc

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise ConfigurationError("Password must not be empty.")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ConfigurationError(
                "Stored credentials cannot be decrypted with the configured key."
            ) from exc
