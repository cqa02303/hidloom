#!/usr/bin/env python3
"""Regression test for logicd's sessiond client helper."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.sessiond_client import SessiondPtyMirrorClient  # noqa: E402
from logicd.logicd import _LazySessiondPtyMirrorClient  # noqa: E402
from logicd.pty_terminal_text import (  # noqa: E402
    DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC,
    WINDOWS_TERMINAL_WSL_CAT_PROFILE,
    build_pty_terminal_text_plan,
)
from sessiond.sessiond import SessiondService  # noqa: E402


def _test_text_plan_profiles_without_socket() -> None:
    editor_client = SessiondPtyMirrorClient("/tmp/not-used.sock")
    first_editor = editor_client.build_text_plans_for_stream("\x1b[2J\x1b[HPWD\r\n")
    second_editor = editor_client.build_text_plans_for_stream("NEXT\r\n")
    assert sum(1 for plan in first_editor if plan.get("receiver") is True) == 0, first_editor
    assert sum(1 for plan in second_editor if plan.get("receiver") is True) == 0, second_editor
    assert any(plan.get("wrapper") == "text_editor_direct_input" for plan in first_editor), first_editor
    assert any("csi_sequence_stripped" in plan.get("stripped_reasons", []) for plan in first_editor), first_editor

    cat_client = SessiondPtyMirrorClient(
        "/tmp/not-used.sock",
        host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE,
    )
    first_cat = cat_client.build_text_plans_for_stream("\x1b[2J\x1b[HPWD\r\n")
    second_cat = cat_client.build_text_plans_for_stream("NEXT\r\n")
    assert sum(1 for plan in first_cat if plan.get("receiver") is True) == 1, first_cat
    assert sum(1 for plan in second_cat if plan.get("receiver") is True) == 0, second_cat
    assert any(plan.get("wrapper") == "direct_hid_ansi" for plan in first_cat), first_cat


def _test_lazy_client_exports_output_methods() -> None:
    lazy = _LazySessiondPtyMirrorClient("/tmp/not-used.sock")
    assert isinstance(getattr(lazy, "host_profile", None), str)
    assert callable(getattr(lazy, "build_text_plans_for_stream", None))
    assert callable(getattr(lazy, "poll_output", None))
    assert callable(getattr(lazy, "watch_output", None))
    plans = lazy.build_text_plans_for_stream("A")
    assert any(plan.get("available") for plan in plans), plans


def _test_direct_output_newlines_have_gap() -> None:
    plan = build_pty_terminal_text_plan("/tmp/path\r\nprompt $ ")
    newline_taps = [
        tap
        for tap in plan.get("taps", [])
        if isinstance(tap, dict) and tap.get("key") == "KC_ENTER"
    ]
    assert newline_taps, plan
    assert all(tap.get("post_gap_sec") == DIRECT_OUTPUT_NEWLINE_POST_GAP_SEC for tap in newline_taps), plan


def _direct_plan_texts(response: dict) -> list[str]:
    texts = []
    for plan in response.get("text_plans", []):
        if plan.get("receiver"):
            continue
        chars = [str(tap.get("char", "")) for tap in plan.get("taps", []) if isinstance(tap, dict)]
        texts.append("".join(chars))
    return texts


async def _poll_until_text(client: SessiondPtyMirrorClient, needle: str, *, attempts: int = 40) -> dict:
    last: dict = {}
    for _ in range(attempts):
        last = await client.poll_output()
        if any(needle in text for text in _direct_plan_texts(last)):
            return last
        await asyncio.sleep(0.025)
    raise AssertionError(f"PTY output {needle!r} not received: {last!r}")


async def _response_or_poll_until_text(client: SessiondPtyMirrorClient, response: dict, needle: str) -> dict:
    if any(needle in text for text in _direct_plan_texts(response)):
        return response
    return await _poll_until_text(client, needle)


async def _poll_until_inactive(client: SessiondPtyMirrorClient, *, attempts: int = 40) -> dict:
    last: dict = {}
    for _ in range(attempts):
        last = await client.poll_output()
        if any(item.get("active") is False for item in last.get("responses", [])):
            return last
        await asyncio.sleep(0.025)
    raise AssertionError(f"PTY inactive status not received: {last!r}")


async def _run() -> None:
    with tempfile.TemporaryDirectory(prefix="logicd-sessiond-client-") as tmpdir:
        socket_path = str(Path(tmpdir) / "sessiond.sock")
        service = SessiondService(socket_path)
        await service.start()
        client = SessiondPtyMirrorClient(socket_path, read_timeout=2.0)
        try:
            started = await client.start(command="/bin/sh", columns=120, rows=35, source="test")
            assert started["ok"] is True
            assert started["responses"][0]["active"] is True
            prompt = await client.poll_output()
            assert prompt["ok"] is True

            text_plan_batches = [started["text_plans"]]
            for action in ("KC_P", "KC_W", "KC_D", "KC_ENTER"):
                response = await client.send_key_action(action)
                text_plan_batches.append(response["text_plans"])
            response = await _response_or_poll_until_text(client, response, "/")
            assert response["ok"] is True
            assert any(plan["available"] for plan in response["text_plans"]), response
            assert any(plan.get("wrapper") == "text_editor_direct_input" for plan in response["text_plans"]), response
            all_initial_plans = [plan for batch in text_plan_batches for plan in batch]
            assert sum(1 for plan in all_initial_plans if plan.get("receiver") is True) == 0, all_initial_plans

            await client.stop(reason="restart_for_modifier_smoke")
            started = await client.start(command="/bin/sh", columns=120, rows=35, source="test")
            assert started["ok"] is True
            for action in ("KC_E", "KC_C", "KC_H", "KC_O", "KC_SPACE"):
                response = await client.send_key_action(action)
            response = await client.send_key_action("KC_1", modifiers=["KC_LSFT"])
            response = await client.send_key_action("KC_ENTER")
            response = await _response_or_poll_until_text(client, response, "!")
            assert any("!" in text for text in _direct_plan_texts(response)), response

            await client.stop(reason="restart_for_ctrl_c_smoke")
            started = await client.start(command="/bin/sh", columns=120, rows=35, source="test")
            assert started["ok"] is True
            for action in ("KC_S", "KC_L", "KC_E", "KC_E", "KC_P", "KC_SPACE", "KC_2", "KC_ENTER"):
                await client.send_key_action(action)
            await client.send_key_action("KC_C", modifiers=["KC_LCTL"])
            for action in ("KC_E", "KC_C", "KC_H", "KC_O", "KC_SPACE", "KC_O", "KC_K", "KC_ENTER"):
                response = await client.send_key_action(action)
            response = await _response_or_poll_until_text(client, response, "ok")
            assert any("ok" in text for text in _direct_plan_texts(response)), response

            for action in ("KC_E", "KC_X", "KC_I", "KC_T", "KC_ENTER"):
                final = await client.send_key_action(action)
            if not any(item.get("active") is False for item in final.get("responses", [])):
                final = await _poll_until_inactive(client)
            assert any(item.get("active") is False for item in final["responses"]), final

            cat_client = SessiondPtyMirrorClient(
                socket_path,
                read_timeout=2.0,
                host_profile=WINDOWS_TERMINAL_WSL_CAT_PROFILE,
            )
            cat_started = await cat_client.start(command="/bin/sh", columns=120, rows=35, source="test")
            cat_batches = [cat_started["text_plans"]]
            for action in ("KC_E", "KC_C", "KC_H", "KC_O", "KC_SPACE", "KC_C", "KC_A", "KC_T", "KC_ENTER"):
                cat_response = await cat_client.send_key_action(action)
                cat_batches.append(cat_response["text_plans"])
            cat_response = await _response_or_poll_until_text(cat_client, cat_response, "cat")
            cat_batches.append(cat_response["text_plans"])
            cat_initial_plans = [plan for batch in cat_batches for plan in batch]
            assert sum(1 for plan in cat_initial_plans if plan.get("receiver") is True) == 1, cat_initial_plans
            assert any(plan.get("wrapper") == "direct_hid_ansi" for plan in cat_initial_plans), cat_initial_plans
            await cat_client.stop(reason="cat_profile_done")

            watch_client = SessiondPtyMirrorClient(socket_path, read_timeout=2.0)
            watch_started = await watch_client.start(command="/bin/sh", columns=120, rows=35, source="test")
            assert watch_started["ok"] is True
            watch_results: list[dict] = []

            async def collect_watch(result: dict) -> None:
                watch_results.append(result)
                if any("watchok" in text for text in _direct_plan_texts(result)):
                    await watch_client.stop(reason="watch_done")

            watch_task = asyncio.create_task(watch_client.watch_output(collect_watch, interval_ms=10))
            for action in ("KC_E", "KC_C", "KC_H", "KC_O", "KC_SPACE", "KC_W", "KC_A", "KC_T", "KC_C", "KC_H", "KC_O", "KC_K", "KC_ENTER"):
                await watch_client.send_key_action(action)
            await asyncio.wait_for(watch_task, timeout=2.0)
            assert any("watchok" in text for result in watch_results for text in _direct_plan_texts(result)), watch_results
        finally:
            await service.close()

    with tempfile.TemporaryDirectory(prefix="logicd-sessiond-client-bad-") as tmpdir:
        socket_path = str(Path(tmpdir) / "bad.sock")

        async def bad_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(b"not-json\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(bad_server, path=socket_path)
        try:
            client = SessiondPtyMirrorClient(socket_path, read_timeout=0.2)
            broken = await client.status()
            assert broken["ok"] is False
            assert broken["responses"] == []
            assert broken["text_plans"] == []
            assert "invalid" in broken["error"].lower(), broken
        finally:
            server.close()
            await server.wait_closed()

    with tempfile.TemporaryDirectory(prefix="logicd-sessiond-client-fast-ack-") as tmpdir:
        socket_path = str(Path(tmpdir) / "fast.sock")

        async def ack_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(
                b'{"schema":"sessiond.protocol.v1","type":"pty_status","active":true,"reason":"input"}\n'
            )
            await writer.drain()
            await asyncio.sleep(1.0)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(ack_server, path=socket_path)
        try:
            client = SessiondPtyMirrorClient(socket_path, read_timeout=0.8)
            started_at = asyncio.get_running_loop().time()
            ack = await client.send_key_action("KC_A")
            elapsed = asyncio.get_running_loop().time() - started_at
            assert ack["ok"] is True, ack
            assert elapsed < 0.25, elapsed
        finally:
            server.close()
            await server.wait_closed()


def main() -> None:
    _test_text_plan_profiles_without_socket()
    _test_lazy_client_exports_output_methods()
    _test_direct_output_newlines_have_gap()
    if sys.platform == "cygwin":
        print("skip: asyncio Unix socket client hangs on this Cygwin/MSYS runtime")
        return
    asyncio.run(_run())
    print("ok: logicd sessiond client defaults to editor plans and supports cat receiver plans")


if __name__ == "__main__":
    main()
