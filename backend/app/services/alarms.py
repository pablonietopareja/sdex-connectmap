from __future__ import annotations

from collections.abc import Iterable

from app.models.schemas import (
    ActiveAlarm,
    AlarmSeverity,
    ConnectionStatus,
    ModuleStatus,
    TopologySnapshot,
)


def deduplicate_alarms(alarms: Iterable[ActiveAlarm]) -> list[ActiveAlarm]:
    """Return one deterministic active alarm per stable alarm id."""

    unique: dict[str, ActiveAlarm] = {}
    for alarm in alarms:
        unique.setdefault(alarm.id, alarm)
    return sorted(unique.values(), key=lambda alarm: (str(alarm.severity), alarm.id))


def build_active_alarms(
    snapshot: TopologySnapshot,
    *,
    tls_verification_disabled: bool,
) -> list[ActiveAlarm]:
    alarms: list[ActiveAlarm] = []
    timestamp = snapshot.generated_at
    if tls_verification_disabled:
        alarms.append(
            ActiveAlarm(
                id="tls_verification_disabled",
                severity=AlarmSeverity.WARNING,
                title="TLS verification is disabled",
                description=(
                    "The real SDEX session uses the explicitly authorized laboratory "
                    "fallback without certificate verification."
                ),
                source="connection-security",
                occurred_at=timestamp,
            )
        )
    if snapshot.partial:
        alarms.append(
            ActiveAlarm(
                id="partial_discovery",
                severity=AlarmSeverity.WARNING,
                title="Discovery is partial",
                description="One or more SDEX modules are unavailable or restricted.",
                source="discovery",
                occurred_at=timestamp,
            )
        )
    failed_modules = sorted(
        result.module for result in snapshot.module_results if result.status != ModuleStatus.OK
    )
    if failed_modules:
        alarms.append(
            ActiveAlarm(
                id="module_refresh_failed",
                severity=AlarmSeverity.WARNING,
                title="Some SDEX modules could not be refreshed",
                description=(
                    "ConnectMap retained safe last-known data where available. "
                    "No remote configuration was changed."
                ),
                source=", ".join(failed_modules)[:120],
                occurred_at=timestamp,
            )
        )
    if snapshot.stale:
        alarms.append(
            ActiveAlarm(
                id="stale_snapshot",
                severity=AlarmSeverity.WARNING,
                title="Topology snapshot is stale",
                description="The displayed source topology is the last safe known snapshot.",
                source="discovery",
                occurred_at=timestamp,
            )
        )
    if snapshot.stale and snapshot.gateway.status == ConnectionStatus.UNKNOWN:
        alarms.append(
            ActiveAlarm(
                id="sdex_unreachable",
                severity=AlarmSeverity.ERROR,
                title="SDEX is unreachable",
                description="ConnectMap cannot currently communicate with the SDEX gateway.",
                source="core",
                occurred_at=timestamp,
            )
        )
    return deduplicate_alarms(alarms)
