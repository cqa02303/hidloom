"""Fan-out output router for keyboard HID reports.

Outputs are treated as independently enabled connections instead of one selected
destination. Each enabled backend receives the same 8-byte keyboard HID report.

The router also exposes a small force_* control surface for key actions such as
KC_USB / KC_CONSOLE / KC_BT. These controls select one explicit backend and stop
the auto backend.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

ReportWriter = Callable[[bytes], None]
BtDisabledHook = Callable[[], None]
TargetChangedHook = Callable[[str], None]
NULL_KEYBOARD_REPORT = bytes(8)


class KeyboardOutputBackend(Protocol):
    name: str
    enabled: bool

    def write(self, report: bytes) -> None:
        """Write one keyboard HID report."""

    def check(self) -> None:
        """Refresh connection state if this backend has one."""

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable this backend."""


@dataclass
class CallableOutputBackend:
    """Adapter for existing report writer callables."""

    name: str
    writer: ReportWriter
    enabled: bool = True

    def write(self, report: bytes) -> None:
        if self.enabled:
            self.writer(report)

    def check(self) -> None:
        fn = getattr(self.writer, "check_and_switch", None)
        if fn is not None:
            fn()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def send(self, report: bytes) -> bool:
        if not self.enabled:
            return False
        try:
            self.write(report)
            return True
        except Exception as exc:
            log.warning("output backend %s failed: %s", self.name, exc)
            return False

class DebugOutputBackend:
    """Debug backend that logs reports instead of writing to a device."""

    name = "debug"

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def write(self, report: bytes) -> None:
        if self.enabled:
            log.info("DebugOutput: report=%s", report.hex())

    def check(self) -> None:
        return None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class BluetoothHidOutputBackend:
    """Bluetooth HID backend adapter.

    The BLE HID transport is owned by btd.  logicd only forwards
    the canonical 8-byte keyboard HID report to the injected sender.  If btd is
    unavailable, the sender may drop reports without affecting other backends.
    """

    name = "bt"

    def __init__(self, sender: ReportWriter | None = None, *, enabled: bool = False) -> None:
        self.sender = sender
        self.enabled = enabled

    def write(self, report: bytes) -> None:
        if not self.enabled:
            return
        if self.sender is None:
            log.debug("Bluetooth HID sender is not configured: report=%s", report.hex())
            return
        self.sender(report)

    def check(self) -> None:
        return None

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class OutputRouter:
    """Fan-out router for keyboard HID reports."""

    def __init__(
        self,
        backends: Iterable[KeyboardOutputBackend] | None = None,
        *,
        on_bt_disabled: BtDisabledHook | None = None,
        on_target_changed: TargetChangedHook | None = None,
    ) -> None:
        self._backends: dict[str, KeyboardOutputBackend] = {}
        self._targets: tuple[str, ...] = ()
        self._on_bt_disabled = on_bt_disabled
        self._on_target_changed = on_target_changed
        if backends is not None:
            for backend in backends:
                self.register(backend)
            self.set_targets(backend.name for backend in backends)

    def register(self, backend: KeyboardOutputBackend) -> None:
        self._backends[backend.name] = backend

    def unregister(self, name: str) -> None:
        self._backends.pop(name, None)
        self._targets = tuple(target for target in self._targets if target != name)

    def set_targets(self, targets: Iterable[str]) -> None:
        bt_was_enabled = self._is_backend_enabled("bt")
        unique: list[str] = []
        for target in targets:
            if target not in unique:
                unique.append(target)
        self._targets = tuple(unique)
        for name, backend in self._backends.items():
            backend.set_enabled(name in self._targets)
        if bt_was_enabled and not self._is_backend_enabled("bt"):
            self._handle_bt_disabled()

    def set_enabled(self, name: str, enabled: bool) -> bool:
        backend = self._backends.get(name)
        if backend is None:
            return False
        bt_was_enabled = self._is_backend_enabled("bt")
        backend.set_enabled(enabled)
        targets = list(self._targets)
        if enabled and name not in targets:
            targets.append(name)
        elif not enabled:
            targets = [target for target in targets if target != name]
        self._targets = tuple(targets)
        if bt_was_enabled and not self._is_backend_enabled("bt"):
            self._handle_bt_disabled()
        return True

    def targets(self) -> tuple[str, ...]:
        return self._targets

    def enabled_names(self) -> tuple[str, ...]:
        return tuple(target for target in self._targets if self._backends.get(target, None) is not None and self._backends[target].enabled)

    def backend_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends.keys()))

    @property
    def current_mode(self) -> str:
        """Return the effective single output mode when auto is active."""
        if self._targets == ("auto",):
            backend = self._backends.get("auto")
            writer = getattr(backend, "writer", None)
            mode = getattr(writer, "current_mode", None)
            if isinstance(mode, str) and mode:
                return mode
            return "auto"
        if len(self._targets) == 1:
            return self._targets[0]
        return ",".join(self._targets)

    def check(self) -> None:
        for target in self._targets:
            backend = self._backends.get(target)
            if backend is None or not backend.enabled:
                continue
            try:
                backend.check()
            except Exception as exc:
                log.debug("output backend %s check failed: %s", target, exc)

    def send(self, report: bytes) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for target in self._targets:
            backend = self._backends.get(target)
            if backend is None:
                log.debug("output backend not registered: %s", target)
                result[target] = False
                continue
            if not backend.enabled:
                result[target] = False
                continue
            try:
                backend.write(report)
                result[target] = True
            except Exception as exc:
                log.warning("output backend %s failed: %s", target, exc)
                result[target] = False
        return result

    def write(self, report: bytes) -> None:
        self.send(report)

    def __call__(self, report: bytes) -> None:
        self.write(report)

    def check_and_switch(self) -> None:
        """Compatibility hook used by the existing USB monitor loop."""
        self.check()

    def _call_writer_hook(self, backend_name: str, hook_name: str) -> bool:
        """Call a compatibility hook on a backend writer if present."""
        backend = self._backends.get(backend_name)
        writer = getattr(backend, "writer", None)
        hook = getattr(writer, hook_name, None)
        if hook is None:
            return False
        hook()
        return True

    def _is_backend_enabled(self, name: str) -> bool:
        backend = self._backends.get(name)
        return bool(backend is not None and backend.enabled and name in self._targets)

    def _handle_bt_disabled(self) -> None:
        backend = self._backends.get("bt")
        if backend is not None:
            was_enabled = backend.enabled
            try:
                backend.set_enabled(True)
                backend.write(NULL_KEYBOARD_REPORT)
            except Exception as exc:
                log.debug("BT null report before disconnect failed: %s", exc)
            finally:
                backend.set_enabled(was_enabled)
        if self._on_bt_disabled is not None:
            try:
                self._on_bt_disabled()
            except Exception as exc:
                log.warning("BT disabled hook failed: %s", exc)

    def _notify_target_changed(self, target: str) -> None:
        if self._on_target_changed is None:
            return
        try:
            self._on_target_changed(target)
        except Exception as exc:
            log.warning("output target changed hook failed: %s", exc)

    def force_auto(self) -> None:
        """Select automatic single-output backend when available."""
        if "auto" not in self._backends:
            log.warning("auto output backend is not registered")
            return
        self._call_writer_hook("auto", "force_auto")
        self.set_targets(("auto",))
        self._notify_target_changed("auto")
        log.info("OutputRouter: forced output target auto")

    def force_gadget(self) -> None:
        """Force USB gadget output only, disabling auto selection."""
        if "gadget" in self._backends:
            self.set_targets(("gadget",))
            self._notify_target_changed("gadget")
            log.info("OutputRouter: forced output target gadget")
            return
        log.warning("gadget output backend is not registered")

    def force_uinput(self) -> None:
        """Force uinput output only, disabling auto selection."""
        if "uinput" in self._backends:
            self.set_targets(("uinput",))
            self._notify_target_changed("uinput")
            log.info("OutputRouter: forced output target uinput")
            return
        log.warning("uinput output backend is not registered")

    def force_bt(self) -> None:
        """Force Bluetooth output only.

        This intentionally toggles output connection targets, not Bluetooth power
        or pairing state. Bluetooth power/pairing remains controlled by BT_* actions.
        """
        if "bt" not in self._backends:
            log.warning("bt output backend is not registered")
            return
        self.set_targets(("bt",))
        self._notify_target_changed("bt")
        log.info("OutputRouter: forced output target bt")


def parse_output_targets(value: str | Iterable[str] | None, *, default: str = "auto") -> tuple[str, ...]:
    """Parse output target config into a stable tuple.

    Accepts comma/plus/space separated strings such as ``gadget,uinput,debug``
    or an iterable of target names.  ``log``/``logging``/``dummy`` are aliases
    for ``debug``.
    """
    if value is None:
        value = default
    if isinstance(value, str):
        raw = value.replace("+", ",").replace(" ", ",").split(",")
    else:
        raw = list(value)

    targets: list[str] = []
    for part in raw:
        name = str(part).strip().lower()
        if not name:
            continue
        if name in {"log", "logging", "dummy"}:
            name = "debug"
        if name not in targets:
            targets.append(name)
    return tuple(targets)
