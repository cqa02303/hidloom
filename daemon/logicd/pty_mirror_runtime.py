"""Runtime state and routing helpers for logicd PTY mirror mode."""
from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import logging
import re
from typing import Any

PTY_MIRROR_SOURCE = "pty_terminal_input"
log = logging.getLogger(__name__)
_READY_PROMPT_RE = re.compile(r"(?:^|[\r\n])[^\r\n]{1,180}[$#] ?")
_TRACKED_MODIFIERS = frozenset({
    "KC_LSFT",
    "KC_RSFT",
    "KC_LSHIFT",
    "KC_RSHIFT",
    "KC_LCTL",
    "KC_RCTL",
    "KC_LCTRL",
    "KC_RCTRL",
    "KC_LALT",
    "KC_RALT",
    "KC_LGUI",
    "KC_RGUI",
})
_CTRL_MODIFIERS = frozenset({
    "KC_LCTL",
    "KC_RCTL",
    "KC_LCTRL",
    "KC_RCTRL",
})


@dataclass
class PtyMirrorRuntime:
    active: bool = False
    last_reason: str = "idle"
    last_error: str | None = None
    sent_key_actions: int = 0
    text_plan_count: int = 0
    client: Any = None
    last_text_plans: list[dict[str, Any]] = field(default_factory=list)
    active_modifiers: set[str] = field(default_factory=set)
    clear_output_queue_requests: int = 0
    output_poll_task: asyncio.Task | None = None
    output_dispatch_queue: asyncio.Queue | None = None
    output_dispatch_task: asyncio.Task | None = None
    output_stopped_callback: Any = None
    output_poll_interval_sec: float = 0.025
    display_ready: bool = False
    typeahead_text: str = ""

    def bind_client(self, client: Any) -> None:
        self.client = client

    def is_interrupt_action(self, action: str, is_press: bool) -> bool:
        if not self.active or not is_press or action != "KC_C":
            return False
        return bool(self.active_modifiers & _CTRL_MODIFIERS)

    async def start(
        self,
        *,
        command: str = "bash",
        columns: int = 120,
        rows: int = 35,
        source: str = "KC_SH7",
    ) -> dict[str, Any]:
        if self.client is None:
            self.active = False
            self.last_reason = "client_missing"
            self.last_error = "sessiond client is not configured"
            return self.to_dict()
        self.active_modifiers.clear()
        self.sent_key_actions = 0
        self.text_plan_count = 0
        self.clear_output_queue_requests = 0
        self.last_text_plans.clear()
        self.display_ready = False
        self.typeahead_text = ""
        try:
            result = await self.client.start(command=command, columns=columns, rows=rows, source=source)
        except Exception as exc:
            self.active = False
            self.last_reason = "start_failed"
            self.last_error = str(exc)
            return {**self.to_dict(), "text_plans": []}
        self.active = bool(result.get("ok"))
        self.last_reason = "started" if self.active else "start_failed"
        self.last_error = None if self.active else str(result.get("error") or result.get("responses") or "start failed")
        text_plans = self._record_text_plans(result)
        if text_plans:
            self.display_ready = True
        status = self.to_dict()
        status["text_plans"] = text_plans
        return status

    async def stop(self, *, reason: str = "logicd_stop") -> dict[str, Any]:
        stop_error: str | None = None
        if self.client is not None:
            try:
                await self.client.stop(reason=reason)
            except Exception as exc:
                stop_error = str(exc)
        self.active = False
        await self.stop_output_polling()
        self.active_modifiers.clear()
        self.last_text_plans.clear()
        self.display_ready = False
        self.typeahead_text = ""
        self.last_reason = reason
        self.last_error = stop_error
        return self.to_dict()

    def start_output_polling(self, enqueue_text_plans: Any, on_stopped: Any = None) -> None:
        if on_stopped is not None:
            self.output_stopped_callback = on_stopped
        if self.output_poll_task is not None and not self.output_poll_task.done():
            return
        self.output_poll_task = asyncio.create_task(self._poll_output_loop(enqueue_text_plans))

    async def stop_output_polling(self) -> None:
        task = self.output_poll_task
        self.output_poll_task = None
        self.output_stopped_callback = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _poll_output_loop(self, enqueue_text_plans: Any) -> None:
        watch_output = getattr(self.client, "watch_output", None)
        if callable(watch_output):
            try:
                await watch_output(lambda result: self._handle_output_result(result, enqueue_text_plans))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("PTY mirror output watch failed: %s", exc)
                self.active = False
                self.active_modifiers.clear()
                self.last_reason = "output_watch_failed"
                self.last_error = str(exc)
                return
        while self.active:
            await asyncio.sleep(self.output_poll_interval_sec)
            if self.client is None:
                continue
            try:
                result = await self.client.poll_output()
            except Exception as exc:
                log.warning("PTY mirror output poll failed: %s", exc)
                continue
            if self._handle_output_result(result, enqueue_text_plans):
                return

    def _handle_output_result(self, result: dict[str, Any], enqueue_text_plans: Any) -> bool:
        output_result = self._text_plans_for_output_result(result)
        text_plans = self._record_text_plans(output_result) if output_result.get("text_plans") else []
        if text_plans:
            enqueue_text_plans(text_plans)
        for response in result.get("responses", []):
            if response.get("clear_output_queue") is True:
                self.clear_output_queue_requests += 1
            if response.get("type") == "pty_status" and response.get("active") is False:
                self.active = False
                self.active_modifiers.clear()
                self.last_reason = str(response.get("reason") or "exit")
                callback = self.output_stopped_callback
                if callable(callback):
                    callback_result = callback(dict(response))
                    if asyncio.iscoroutine(callback_result):
                        asyncio.create_task(callback_result)
                return True
        return False

    async def route_action(self, action: str, is_press: bool) -> dict[str, Any]:
        """Route a key action to sessiond when mirror mode is active."""
        if not self.active:
            return {"consumed": False, "reason": "inactive"}
        if action in _TRACKED_MODIFIERS:
            if is_press:
                self.active_modifiers.add(action)
            else:
                self.active_modifiers.discard(action)
            return {"consumed": True, "reason": "modifier_state", "active": self.active, "text_plans": []}
        if not is_press:
            return {"consumed": True, "reason": "release_ignored"}
        if self.client is None:
            self.active = False
            self.active_modifiers.clear()
            self.last_reason = "client_missing"
            self.last_error = "sessiond client is not configured"
            return {"consumed": True, "reason": self.last_reason, "active": False}
        active_modifiers = sorted(self.active_modifiers)
        is_interrupt = self.is_interrupt_action(action, is_press)
        try:
            result = await self.client.send_key_action(action, is_press=True, modifiers=active_modifiers)
        except Exception as exc:
            self.active = False
            self.active_modifiers.clear()
            self.last_reason = "sessiond_unavailable"
            self.last_error = str(exc)
            return {"consumed": True, "reason": self.last_reason, "active": False, "text_plans": []}
        self.sent_key_actions += 1
        input_display_plans = self._input_display_plans(action, active_modifiers, is_interrupt=is_interrupt)
        text_plans = input_display_plans + self._record_text_plans(result)
        log.info(
            "PTY mirror input action=%s modifiers=%s responses=%s text_plans=%s ok=%s",
            action,
            active_modifiers,
            [
                {
                    "type": response.get("type"),
                    "active": response.get("active"),
                    "reason": response.get("reason"),
                    "written": response.get("written"),
                    "text_len": len(str(response.get("text", ""))) if "text" in response else 0,
                }
                for response in result.get("responses", [])
                if isinstance(response, dict)
            ],
            len(text_plans),
            result.get("ok"),
        )
        for response in result.get("responses", []):
            if response.get("clear_output_queue") is True:
                self.clear_output_queue_requests += 1
            if response.get("type") == "pty_status" and response.get("active") is False:
                self.active = False
                self.active_modifiers.clear()
                self.last_reason = str(response.get("reason") or "exit")
        if not result.get("ok") and not result.get("responses"):
            self.active = False
            self.active_modifiers.clear()
            self.last_reason = "sessiond_unavailable"
            self.last_error = str(result.get("error") or "sessiond unavailable")
        return {
            "consumed": True,
            "reason": self.last_reason,
            "active": self.active,
            "text_plan_count": self.text_plan_count,
            "text_plans": text_plans,
            "clear_output_queue": is_interrupt or any(
                isinstance(response, dict) and response.get("clear_output_queue") is True
                for response in result.get("responses", [])
            ),
        }

    def _input_display_plans(
        self,
        action: str,
        active_modifiers: list[str],
        *,
        is_interrupt: bool = False,
    ) -> list[dict[str, Any]]:
        from .pty_terminal_text import (
            WINDOWS_TEXT_EDITOR_PROFILE,
            build_pty_terminal_text_plans,
            key_action_to_text_char,
            normalize_pty_terminal_host_profile,
        )

        display_text = key_action_to_text_char(action, active_modifiers)
        raw_host_profile = getattr(self.client, "host_profile", None)
        host_profile = normalize_pty_terminal_host_profile(raw_host_profile) if raw_host_profile else ""
        can_display = (
            not is_interrupt
            and bool(display_text)
            and host_profile == WINDOWS_TEXT_EDITOR_PROFILE
        )
        if action in {"KC_ENTER", "KC_ENT", "KC_RETURN"}:
            if self.display_ready:
                self.display_ready = False
                return build_pty_terminal_text_plans(display_text, host_profile=host_profile) if can_display else []
            if self.typeahead_text:
                self.typeahead_text += display_text
            return []
        if not display_text:
            return []
        if self.display_ready:
            return build_pty_terminal_text_plans(display_text, host_profile=host_profile) if can_display else []
        self.typeahead_text += display_text
        return []

    def _text_plans_for_output_result(self, result: dict[str, Any]) -> dict[str, Any]:
        raw_texts = [
            str(response.get("text", ""))
            for response in result.get("responses", [])
            if isinstance(response, dict) and response.get("type") == "pty_text_stream" and "text" in response
        ]
        if not raw_texts:
            return result
        if not self.typeahead_text:
            if any(_READY_PROMPT_RE.search(text) for text in raw_texts):
                self.display_ready = True
            return result
        builder = getattr(self.client, "build_text_plans_for_stream", None)
        if not callable(builder):
            return result
        text_plans: list[dict[str, Any]] = []
        for text in raw_texts:
            filtered = self._filter_typeahead_output(text)
            if filtered:
                text_plans.extend(builder(filtered))
        copied = dict(result)
        copied["text_plans"] = text_plans
        return copied

    def _filter_typeahead_output(self, text: str) -> str:
        filtered = str(text or "")
        prompt_matches = list(_READY_PROMPT_RE.finditer(filtered))
        if prompt_matches:
            prompt = prompt_matches[-1]
            before_prompt = filtered[: prompt.end()]
            after_prompt = filtered[prompt.end():]
            filtered = before_prompt + after_prompt
            self.display_ready = True
            if self.typeahead_text:
                filtered += self.typeahead_text
                self.typeahead_text = ""
        return filtered

    def _record_text_plans(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        plans = [
            plan
            for plan in result.get("text_plans", [])
            if isinstance(plan, dict) and plan.get("available") is True
        ]
        if not plans:
            self.last_text_plans.clear()
            return []
        self.last_text_plans = plans[-3:]
        self.text_plan_count += len(plans)
        return plans

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "last_reason": self.last_reason,
            "last_error": self.last_error,
            "sent_key_actions": self.sent_key_actions,
            "text_plan_count": self.text_plan_count,
            "clear_output_queue_requests": self.clear_output_queue_requests,
            "active_modifiers": sorted(self.active_modifiers),
            "source": PTY_MIRROR_SOURCE,
        }
