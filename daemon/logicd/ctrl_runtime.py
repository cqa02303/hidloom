"""Runtime routing ctrl JSON-line commands for logicd."""
from __future__ import annotations

from typing import Any

from .ctrl_common import ctrl_error, ctrl_response


async def process_spid_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    t = msg.get("t")
    state = msg.get("state")
    if t == "SPID_CONNECT" or (t == "SPID_STATUS" and state == "ready"):
        if ctx.handle_spid_connect is None:
            await ctrl_error(writer, t, "spid connect is not supported by this logicd")
            return
        socket_path = str(msg.get("socket") or "/tmp/spi_events.sock")
        await ctx.handle_spid_connect(socket_path)
        if writer is not None:
            await ctrl_response(writer, {"t": t, "result": "ok", "socket": socket_path})
        return

    if ctx.handle_spid_disconnect is None:
        await ctrl_error(writer, t, "spid disconnect is not supported by this logicd")
        return
    await ctx.handle_spid_disconnect()
    if writer is not None:
        await ctrl_response(writer, {"t": t, "result": "ok"})


async def process_bt_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    t = msg.get("t")
    if ctx.handle_bt_action is None:
        await ctrl_error(writer, t, "Bluetooth control is not supported by this logicd")
        return
    action = str(msg.get("action") or "")
    if action not in {
        "BT_STATUS",
        "BT_POWER_ON",
        "BT_POWER_OFF",
        "BT_POWER_TOGGLE",
        "BT_PAIRING_ON",
        "BT_PAIRING_OFF",
        "BT_PAIRING_TOGGLE",
        "BT_DISCONNECT",
        "BT_FORGET_DEVICE",
    }:
        await ctrl_error(writer, t, f"invalid Bluetooth action: {action!r}")
        return
    await ctx.handle_bt_action(action)
    if writer is not None:
        await ctrl_response(writer, {"t": "BT", "result": "ok", "action": action})


async def process_output_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    t = msg.get("t")
    if ctx.handle_output_target is None:
        await ctrl_error(writer, t, "output target control is not supported by this logicd")
        return
    target = str(msg.get("target") or msg.get("mode") or "").strip().lower()
    if target in {"console", "kc_console"}:
        target = "uinput"
    elif target in {"usb", "kc_usb"}:
        target = "gadget"
    elif target in {"kc_bt", "bluetooth"}:
        target = "bt"
    elif target == "kc_connauto":
        target = "auto"
    if target not in {"auto", "gadget", "uinput", "bt"}:
        await ctrl_error(writer, t, f"invalid output target: {target!r}")
        return
    await ctx.handle_output_target(target)
    if writer is not None:
        await ctrl_response(writer, {"t": "OUTPUT", "result": "ok", "target": target})
