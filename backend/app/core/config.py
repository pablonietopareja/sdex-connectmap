from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
ALLOWED_REFRESH_INTERVALS = (60, 300, 600, 900, 1800, 3600)
KNOWN_MOCK_SCENARIOS = frozenset(
    {
        "dynamic",
        "stable",
        "visual_preview",
        "editor_preview",
        "partial",
        "missing_modules",
        "offline",
    }
)
CA_CERTIFICATE_SUFFIXES = frozenset({".crt", ".pem"})


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be a boolean")


def normalize_base_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("SDEX base URL is required")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("SDEX base URL has an invalid port") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("SDEX base URL must use http or https")
    if not parsed.hostname:
        raise ValueError("SDEX base URL must include a host")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in parsed.hostname
    ):
        raise ValueError("SDEX base URL host contains invalid characters")
    if port is not None and port < 1:
        raise ValueError("SDEX base URL port must be between 1 and 65535")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials must not be embedded in the SDEX base URL")
    if parsed.query or parsed.fragment:
        raise ValueError("SDEX base URL must not include a query or fragment")
    path = parsed.path.rstrip("/")
    if path not in {"", "/"}:
        raise ValueError("SDEX base URL must not include a path")
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def normalize_ca_cert_path(value: str | Path) -> Path:
    candidate = str(value).strip()
    if not candidate:
        raise ValueError("SDEX_CA_CERT_PATH must not be empty")
    try:
        path = Path(candidate).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("SDEX_CA_CERT_PATH must reference an existing PEM or CRT file") from exc
    if not path.is_file() or path.suffix.lower() not in CA_CERTIFICATE_SUFFIXES:
        raise ValueError("SDEX_CA_CERT_PATH must reference an existing PEM or CRT file")
    return path


def _database_path(data_dir: Path) -> Path:
    raw_url = os.getenv("CONNECTMAP_DATABASE_URL")
    if not raw_url:
        return data_dir / "connectmap.db"
    prefix = "sqlite:///"
    if not raw_url.startswith(prefix):
        raise ValueError("CONNECTMAP_DATABASE_URL must use sqlite:///")
    raw_path = raw_url[len(prefix) :]
    if raw_path.startswith("/") and os.name == "nt" and len(raw_path) > 2 and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return Path(raw_path)


@dataclass(frozen=True, slots=True)
class AppSettings:
    host: str
    port: int
    data_dir: Path
    database_path: Path
    secret_key: str | None
    log_level: str
    mock_mode: bool
    mock_scenario: str
    default_refresh_seconds: int
    request_timeout_seconds: float
    max_concurrency: int
    disable_docs: bool
    static_dir: Path | None
    max_body_bytes: int
    sdex_base_url: str | None
    sdex_username: str | None
    sdex_password: str | None
    sdex_verify_tls: bool
    sdex_ca_cert_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("CONNECTMAP_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("CONNECTMAP_PORT must be between 1 and 65535")
        if self.default_refresh_seconds not in ALLOWED_REFRESH_INTERVALS:
            raise ValueError("CONNECTMAP_DEFAULT_REFRESH_SECONDS is not supported")
        if not 1 <= self.request_timeout_seconds <= 120:
            raise ValueError("CONNECTMAP_REQUEST_TIMEOUT_SECONDS must be between 1 and 120")
        if not 1 <= self.max_concurrency <= 32:
            raise ValueError("CONNECTMAP_MAX_CONCURRENCY must be between 1 and 32")
        if self.max_body_bytes <= 0:
            raise ValueError("CONNECTMAP_MAX_BODY_BYTES must be greater than zero")
        if self.mock_scenario not in KNOWN_MOCK_SCENARIOS:
            raise ValueError(
                "CONNECTMAP_MOCK_SCENARIO must be one of " + ", ".join(sorted(KNOWN_MOCK_SCENARIOS))
            )
        if self.sdex_ca_cert_path is not None:
            object.__setattr__(
                self,
                "sdex_ca_cert_path",
                normalize_ca_cert_path(self.sdex_ca_cert_path),
            )

    @classmethod
    def from_env(cls) -> AppSettings:
        configured_data_dir = os.getenv("CONNECTMAP_DATA_DIR")
        if configured_data_dir:
            data_dir = Path(configured_data_dir).expanduser()
        elif os.name == "nt":
            data_dir = Path.cwd() / ".connectmap-data"
        else:
            data_dir = Path("/data")
        interval = int(os.getenv("CONNECTMAP_DEFAULT_REFRESH_SECONDS", "300"))
        if interval not in ALLOWED_REFRESH_INTERVALS:
            raise ValueError(
                "CONNECTMAP_DEFAULT_REFRESH_SECONDS must be one of "
                + ", ".join(str(value) for value in ALLOWED_REFRESH_INTERVALS)
            )
        static_value = os.getenv("CONNECTMAP_STATIC_DIR")
        base_url_value = os.getenv("SDEX_BASE_URL", "").strip()
        ca_cert_value = os.getenv("SDEX_CA_CERT_PATH", "").strip()
        return cls(
            host=os.getenv("CONNECTMAP_HOST", "127.0.0.1"),
            port=int(os.getenv("CONNECTMAP_PORT", "8080")),
            data_dir=data_dir,
            database_path=_database_path(data_dir),
            secret_key=os.getenv("CONNECTMAP_SECRET_KEY") or None,
            log_level=os.getenv("CONNECTMAP_LOG_LEVEL", "INFO").upper(),
            mock_mode=env_bool("CONNECTMAP_MOCK_MODE", False),
            mock_scenario=os.getenv("CONNECTMAP_MOCK_SCENARIO", "dynamic").strip().lower(),
            default_refresh_seconds=interval,
            request_timeout_seconds=float(os.getenv("CONNECTMAP_REQUEST_TIMEOUT_SECONDS", "15")),
            max_concurrency=int(os.getenv("CONNECTMAP_MAX_CONCURRENCY", "4")),
            disable_docs=env_bool("CONNECTMAP_DISABLE_DOCS", False),
            static_dir=Path(static_value) if static_value else None,
            max_body_bytes=int(os.getenv("CONNECTMAP_MAX_BODY_BYTES", str(256 * 1024))),
            sdex_base_url=normalize_base_url(base_url_value) if base_url_value else None,
            sdex_username=os.getenv("SDEX_USERNAME") or None,
            sdex_password=os.getenv("SDEX_PASSWORD") or None,
            sdex_verify_tls=env_bool("SDEX_VERIFY_TLS", True),
            sdex_ca_cert_path=(normalize_ca_cert_path(ca_cert_value) if ca_cert_value else None),
        )

    @property
    def environment_profile_complete(self) -> bool:
        return bool(self.sdex_base_url and self.sdex_username and self.sdex_password)
