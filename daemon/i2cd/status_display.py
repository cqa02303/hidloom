"""Small daemon-status display helpers shared by i2cd and tests."""
from __future__ import annotations

DAEMON_STATUS_ICONS: tuple[tuple[str, str], ...] = (
    ("matrixd", "mtx"),
    ("logicd-core", "core"),
    ("logicd-companion", "cmp"),
    ("outputd", "out"),
    ("uidd", "uid"),
    ("ledd", "led"),
    ("btd", "btd"),
    ("httpd", "web"),
    ("hidd", "hid"),
    ("viald", "vial"),
)


def daemon_status_active(statuses: dict[str, bool], service: str) -> bool:
    if service == "logicd-core":
        return bool(statuses.get("logicd-core", statuses.get("logicd", False)))
    if service == "logicd-companion":
        return bool(statuses.get("logicd-companion", statuses.get("logicd", False)))
    if service == "hidd":
        return bool(statuses.get("hidd", statuses.get("usbd", False)))
    return bool(statuses.get(service, False))


def daemon_status_icon_row(statuses: dict[str, bool]) -> list[tuple[str, bool]]:
    return [(icon_name, daemon_status_active(statuses, service)) for service, icon_name in DAEMON_STATUS_ICONS]
