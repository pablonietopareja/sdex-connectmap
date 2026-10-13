from __future__ import annotations

from typing import Any


class ConnectMapError(Exception):
    code = "connectmap_error"
    status_code = 500
    public_message = "The operation could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.public_message)
        self.details = details


class ConfigurationError(ConnectMapError):
    code = "invalid_configuration"
    status_code = 400
    public_message = "The SDEX configuration is invalid."


class NotConfiguredError(ConnectMapError):
    code = "not_configured"
    status_code = 409
    public_message = "SDEX is not configured."


class ResourceNotFoundError(ConnectMapError):
    code = "resource_not_found"
    status_code = 404
    public_message = "The requested topology resource does not exist."


class TopologyConflictError(ConnectMapError):
    code = "topology_conflict"
    status_code = 409
    public_message = "The visual topology change conflicts with the current topology."


class AuthenticationError(ConnectMapError):
    code = "sdex_authentication_failed"
    status_code = 502
    public_message = "SDEX authentication failed. Check the username and password."


class PermissionDeniedError(ConnectMapError):
    code = "sdex_permission_denied"
    status_code = 502
    public_message = "The SDEX user does not have permission for this operation."


class DefaultPasswordError(ConnectMapError):
    code = "sdex_default_password"
    status_code = 502
    public_message = (
        "SDEX rejected the request because the default administrator password "
        "must be changed in SDEX."
    )


class SDEXUnavailableError(ConnectMapError):
    code = "sdex_unavailable"
    status_code = 502
    public_message = "ConnectMap could not communicate with SDEX."


class SDEXResponseError(ConnectMapError):
    code = "sdex_response_error"
    status_code = 502
    public_message = "SDEX returned an unexpected response."


class SDEXParseError(ConnectMapError):
    code = "sdex_parse_error"
    status_code = 502
    public_message = "SDEX returned data that could not be parsed."


class RateLimitError(ConnectMapError):
    code = "rate_limited"
    status_code = 429
    public_message = "Too many requests. Please wait before trying again."
