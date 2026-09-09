"""Ordered native-owner/companion interaction protocol.

Only the native owner commits layer operations. The facade applies each operation
locally first so a due LT hold can resolve the following key in the same turn.
No synchronous core request is made while native waits for this acknowledgement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .keymap import LayerManager
from .action_expansion import expand_action_event
from .input_events import handle_resolved_action, _resolved_event_gap_sec, _EXPANDED_ACTION_STEP_GAP_SEC

log = logging.getLogger(__name__)


class DelegateLayers(LayerManager):
    def begin(self, message):
        self.replace_layers(message["layers"])
        state = message["layer_state"]
        self._default_layer = int(state.get("default", 0))
        for field in ("momentary", "toggled", "oneshot", "locked"):
            setattr(self, "_" + field, set(state.get(field, [])))
        self.operations = []
        self.event_owner = (message.get("source", 0), message.get("row", 0), message.get("col", 0))

    def set_event_owner(self, owner, row, col):
        self.event_owner = (int(owner) if str(owner).isdigit() else owner, row, col)
        super().set_event_owner(owner, row, col)

    def _record(self, op, layer=0, is_press=True):
        source, row, col = self.event_owner
        event = {"op": op, "layer": layer, "is_press": is_press, "source": source, "row": row, "col": col}
        # LT activation updates lookup immediately, then dispatches the same MO.
        # The same contribution may be registered once in an owner turn.
        if op != "mo" or not self.operations or self.operations[-1] != event:
            self.operations.append(event)

    def momentary_on(self, layer):
        super().momentary_on(layer)
        self._record("mo", layer)

    def momentary_off(self, layer):
        super().momentary_off(layer)
        self._record("mo", layer, False)

    def toggle(self, layer):
        super().toggle(layer)
        self._record("tg", layer)

    def to_layer(self, layer):
        # Base implementation calls oneshot_clear; retain one canonical op.
        start = len(self.operations)
        super().to_layer(layer)
        del self.operations[start:]
        self._record("to", layer)

    def set_default(self, layer):
        start = len(self.operations)
        super().set_default(layer)
        del self.operations[start:]
        self._record("df", layer)

    def oneshot_on(self, layer):
        super().oneshot_on(layer)
        self._record("osl", layer)

    def oneshot_clear(self):
        if self.has_oneshot():
            super().oneshot_clear()
            self._record("consume_oneshot")

    def layer_lock_toggle_current(self):
        target = super().layer_lock_toggle_current()
        if target is not None:
            self._record("lock", target, target in self._locked)
        return target

    def locked_clear(self):
        super().locked_clear()
        self._record("clear_locks")


class DelegateSession:
    def __init__(self, context):
        self.context = context
        self.epoch = None
        self.last_event = -1
        self.last_ack = None
        self.lock = asyncio.Lock()
        self.background = {}
        self.active_connection = None
        self.background_error = ""

    async def _cancel_source(self, source=None):
        cancel_output = getattr(self.context().macros, "cancel_output_source", None)
        if cancel_output:
            if source is not None:
                cancel_output(source)
            else:
                for owner in self.context().interactions._owners:
                    cancel_output(owner)
        tasks = [task for owner, pending in self.background.items() if source is None or owner == source for task in pending]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if source is None:
            self.background.clear()
        else:
            self.background.pop(source, None)

    def _defer(self, action, is_press, ctx, *, matrix_key, source, owner):
        previous = list(self.background.get(owner, ()))
        async def run():
            if previous:
                await asyncio.gather(*previous, return_exceptions=True)
            await handle_resolved_action(action, is_press, ctx, matrix_key=matrix_key, source=source, owner=owner)
        task = asyncio.create_task(run())
        pending = self.background.setdefault(owner, set())
        pending.add(task)
        def done(completed):
            pending.discard(completed)
            if not completed.cancelled():
                error = completed.exception()
                if error is not None:
                    self.background_error = f"macro output failed: {type(error).__name__}"
                    log.error(self.background_error)
        task.add_done_callback(done)

    async def process(self, message, *, incarnation=None):
        async with self.lock:
            if incarnation is not None and self.active_connection is not incarnation:
                raise ValueError("superseded delegate connection")
            if message.get("protocol") != 2 or message.get("t") not in {"delegate_event", "delegate_tick", "delegate_source_end"}:
                raise ValueError("unsupported delegate protocol")
            event_id = int(message["event_id"])
            epoch = message["owner_epoch"]
            if epoch == self.epoch and event_id == self.last_event:
                return self.last_ack
            if epoch == self.epoch and event_id < self.last_event:
                raise ValueError("stale delegate event")
            ctx = self.context()
            if self.epoch is not None and epoch != self.epoch:
                # The old native owner has exited and already lost its output
                # ownership. Discard stale companion timers rather than re-emit.
                await self._cancel_source()
                ctx.interactions.reset()
            self.epoch = epoch
            layers = ctx.layers
            if not isinstance(layers, DelegateLayers):
                layers.__class__ = DelegateLayers
            layers.begin(message)
            now = float(message["now_ms"]) / 1000.0 if "now_ms" in message else time.monotonic()
            source = str(message.get("source", 0))
            row, col = message.get("row", 0), message.get("col", 0)
            layers.set_event_owner(source, row, col)
            events = ctx.interactions.on_tick(now)
            if message["t"] == "delegate_event":
                layers.set_event_owner(source, row, col)
                events.extend(ctx.interactions.on_key(row, col, bool(message["is_press"]), now,
                    owner=source, action=message.get("action")))
            elif message["t"] == "delegate_source_end":
                await self._cancel_source(source)
                events.extend(ctx.interactions.clear_owner(source))
            key_events = []
            delay_before_ms = 0
            async def capture(action, is_press, matrix_key, flow_source, owner):
                nonlocal delay_before_ms
                key_events.append({"id": json.dumps([owner, matrix_key, action], separators=(",", ":")),
                                   "action": action, "is_press": is_press, "source": int(owner),
                                   "delay_before_ms": delay_before_ms})
                delay_before_ms = 0
            previous_capture = ctx.core_key_event_owned_fn
            ctx.core_key_event_owned_fn = capture
            try:
                for index, event in enumerate(events):
                    layers.set_event_owner(event.owner, event.row, event.col)
                    steps = expand_action_event(event.action, event.is_press)
                    for step_index, step in enumerate(steps):
                        kwargs = {"matrix_key": (event.row, event.col) if event.row is not None else None,
                                  "source": event.source, "owner": event.owner}
                        if step.action.startswith(("MACRO:", "U+")) or step.action in {"IME_ON", "IME_OFF"}:
                            self._defer(step.action, step.is_press, ctx, **kwargs)
                        else:
                            await handle_resolved_action(step.action, step.is_press, ctx, **kwargs)
                        if step_index + 1 < len(steps):
                            delay_before_ms += round(_EXPANDED_ACTION_STEP_GAP_SEC * 1000)
                    next_event = events[index + 1] if index + 1 < len(events) else None
                    delay_before_ms += round(_resolved_event_gap_sec(event, next_event) * 1000)
            finally:
                ctx.core_key_event_owned_fn = previous_capture
            pending_output = any(self.background.values()) or bool(getattr(ctx.macros, "has_pending_output", lambda: False)())
            next_due = ctx.interactions.next_timer_due()
            if pending_output:
                next_due = min(next_due, now + 0.010) if next_due is not None else now + 0.010
            ack = {"t": "delegate_ack", "protocol": 2, "event_id": event_id,
                   **{key: message[key] for key in ("owner_epoch", "keymap_revision", "layer_revision")},
                   "layer_ops": layers.operations, "key_events": key_events,
                   "context_active": ctx.interactions.has_pending_context() or pending_output,
                   "next_tick_ms": round(next_due * 1000) if next_due is not None else None,
                   "companion_error": self.background_error}
            self.last_event, self.last_ack = event_id, ack
            return ack

    async def handle_client(self, reader, writer):
        incarnation = object()
        async with self.lock:
            self.active_connection = incarnation
            await self._cancel_source()
            self.context().interactions.reset()
        try:
            while line := await reader.readline():
                if self.active_connection is not incarnation:
                    break
                response = await self.process(json.loads(line), incarnation=incarnation)
                writer.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                await writer.drain()
        except (OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            async with self.lock:
                if self.active_connection is incarnation:
                    await self._cancel_source()
                    self.context().interactions.reset()
                    self.active_connection = None
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
