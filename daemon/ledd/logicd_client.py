"""logicd event socket client for ledd."""

from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any

logger = logging.getLogger("ledd")


def _bool_from_message(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes", "active"}
    return False


def handle_logicd_message(line: str, manager: Any) -> None:
    """Parse one JSON-lines message from logicd and dispatch it to manager."""
    if not line:
        return
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("不正な JSON: %r", line)
        return
    if not isinstance(msg, dict):
        logger.warning("不正な JSON root: %s line=%r", type(msg).__name__, line)
        return

    t = msg.get("t")
    if t == "layer":
        try:
            active = msg.get("active")
            if isinstance(active, list) and hasattr(manager, "on_layer_state"):
                layers = [int(layer) for layer in active]
                logger.debug("レイヤー状態変更: %s", layers)
                manager.on_layer_state(layers)
                return
            layer = int(msg.get("layer", active[0] if isinstance(active, list) and active else 0))
            logger.debug("レイヤー変更: %s", layer)
            if hasattr(manager, "set_active_layer"):
                manager.set_active_layer(layer)
            elif hasattr(manager, "on_layer_state"):
                manager.on_layer_state([layer])
        except (TypeError, ValueError) as exc:
            logger.warning("不正な layer メッセージ: %s msg=%r", exc, msg)
    elif t in {"led_state", "lock_state", "led_overlay_state", "state_overlay"}:
        try:
            name = str(msg.get("state") or msg.get("name") or "")
            active = _bool_from_message(msg.get("active", msg.get("on", msg.get("enabled", False))))
            if not name:
                raise ValueError("missing state name")
            if hasattr(manager, "set_state_overlay"):
                manager.set_state_overlay(name, active)
            elif hasattr(manager, "set_semantic_overlay_state"):
                manager.set_semantic_overlay_state(name, active)
        except (TypeError, ValueError) as exc:
            logger.warning("不正な LED state メッセージ: %s msg=%r", exc, msg)
    elif t in {"semantic_roles_reload", "led_semantic_reload"}:
        if hasattr(manager, "request_semantic_roles_reload"):
            manager.request_semantic_roles_reload()
        elif hasattr(manager, "reload_semantic_roles"):
            manager.reload_semantic_roles()
    elif t == "semantic_roles":
        try:
            semantic_roles = msg.get("semantic_roles")
            if not isinstance(semantic_roles, dict):
                raise ValueError("semantic_roles must be an object")
            if hasattr(manager, "apply_semantic_roles"):
                manager.apply_semantic_roles(semantic_roles)
        except (TypeError, ValueError) as exc:
            logger.warning("不正な semantic_roles メッセージ: %s msg=%r", exc, msg)
    elif t == "semantic_keymap":
        try:
            layers = msg.get("layers")
            if not isinstance(layers, list):
                raise ValueError("layers must be a list")
            if hasattr(manager, "apply_semantic_keymap"):
                manager.apply_semantic_keymap(layers)
        except (TypeError, ValueError) as exc:
            logger.warning("不正な semantic_keymap メッセージ: %s msg=%r", exc, msg)
    elif t == "mode":
        logger.debug("出力モード通知: %s", msg.get("mode"))
    elif t == "bt_pairing":
        try:
            manager.apply_bt_pairing_indicator(
                str(msg.get("phase", "off")),
                str(msg.get("digits", "")),
            )
        except Exception as exc:
            logger.warning("不正な bt_pairing メッセージ: %s msg=%r", exc, msg)
    elif t == "morse_feedback":
        try:
            manager.on_morse_feedback(msg)
        except Exception as exc:
            logger.warning("不正な morse_feedback メッセージ: %s msg=%r", exc, msg)
    elif t == "key":
        try:
            kind = str(msg.get("kind", ""))
            row = int(msg["row"])
            col = int(msg["col"])
            if kind not in {"P", "R"}:
                raise ValueError(f"invalid key kind: {kind!r}")
            manager.on_key_event(row, col, kind == "P")
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("不正な key メッセージ: %s msg=%r", exc, msg)
    elif t == "anim":
        try:
            anim_id = int(msg["id"])
            manager.switch(anim_id)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("不正な anim メッセージ: %s msg=%r", exc, msg)
    elif t == "vialrgb":
        try:
            manager.apply_vialrgb(
                int(msg["mode"]),
                int(msg["speed"]),
                int(msg["h"]),
                int(msg["s"]),
                int(msg["v"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("不正な vialrgb メッセージ: %s msg=%r", exc, msg)
    elif t == "vialrgb_direct":
        try:
            manager.apply_vialrgb_direct(
                int(msg["first"]),
                msg["pixels"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("不正な vialrgb_direct メッセージ: %s msg=%r", exc, msg)
    elif t == "vialrgb_direct_pattern":
        try:
            manager.apply_vialrgb_direct_pattern(
                str(msg["pattern"]),
                float(msg["fps"]),
                int(msg["brightness"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("不正な vialrgb_direct_pattern メッセージ: %s msg=%r", exc, msg)
    else:
        logger.warning("不明なメッセージタイプ: %r msg=%r", t, msg)


def logicd_receiver(
    sock_path: str,
    manager: Any,
    stop_event: threading.Event,
) -> None:
    """Connect to logicd's ledd socket and receive events until stopped."""
    reconnect_interval = 3.0

    while not stop_event.is_set():
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(sock_path)
            logger.info("logicd に接続しました: %s", sock_path)

            buf = b""
            while not stop_event.is_set():
                data = sock.recv(4096)
                if not data:
                    logger.info("logicd との接続が切れました")
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    handle_logicd_message(line.decode(errors="ignore").strip(), manager)

        except (ConnectionRefusedError, FileNotFoundError):
            logger.debug(
                "logicd に接続できません (%s)。%s 秒後に再試行",
                sock_path,
                reconnect_interval,
            )
        except OSError as exc:
            logger.warning("logicd 接続エラー: %s", exc)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

        if not stop_event.is_set():
            stop_event.wait(reconnect_interval)
