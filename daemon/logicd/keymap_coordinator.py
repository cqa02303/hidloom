"""Serialize keymap mutations, running-owner acknowledgement, and disk saves."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from .config_loader import keymap_json_to_layers
from .keymap import LayerManager
from .keymap_store import save_runtime_keymap

MUTATIONS = {"M", "S", "LAYER_ADD", "LAYER_CLEAR", "RESET_KEYMAP", "KEYMAP_COMPARE_APPLY"}


class UnknownOwnerOutcome(RuntimeError):
    """The owner may have committed, but its retained result cannot be read."""


class KeymapCoordinator:
    def __init__(self, layers, runtime_path, default_path, matrix_in_range, *, native_request=None):
        self.layers = layers
        self.runtime_path = Path(runtime_path)
        self.default_path = Path(default_path)
        self.matrix_in_range = matrix_in_range
        self.native_request = native_request
        self.lock = asyncio.Lock()
        self.owner_epoch = uuid.uuid4().hex
        self.revision = 0
        self.persisted_revision = 0
        self.owner_ack = None
        self.operations = {}

    def snapshot(self):
        return {"coordinator_epoch": self.owner_epoch, "runtime_revision": self.revision, "persisted_revision": self.persisted_revision,
                "persisted": self.revision == self.persisted_revision, "owner": self.owner_ack}

    async def control(self, message):
        """Guard forwarding and mutations share one coordinator serialization point."""
        async with self.lock:
            kind = message.get("t")
            try:
                if kind == "CONTROL_OWNER":
                    owner = await self._owner_state() if self.native_request else {
                        "owner_epoch": self.owner_epoch, "keymap_revision": self.revision,
                        "capabilities": [], "owner_kind": "python", "guarded_tap_supported": False}
                    if self.native_request and "row" in message and "col" in message:
                        owner = await self.native_request({"t": "owner_state", "row": message["row"], "col": message["col"], "include_keymap": True})
                        if owner.get("layers") != self.layers.layers_snapshot():
                            raise RuntimeError("native and companion keymap mismatch")
                    return {"result": "ok", **self.snapshot(), "owner": owner,
                            "capabilities": ["keymap_compare_apply", *owner.get("capabilities", [])]}
                if not self.native_request:
                    raise ValueError("guarded tap unsupported by Python owner; normal input sessions remain available")
                if kind == "GUARDED_OPERATION":
                    return await self.native_request({"t": "operation_status", "operation_id": message["operation_id"]})
                if kind != "GUARDED_TAP":
                    raise ValueError("unknown owner command")
                if self.revision != self.persisted_revision:
                    raise ValueError("keymap has unpersisted changes")
                if message.get("expected_coordinator_epoch") != self.owner_epoch or message.get("expected_runtime_revision") != self.revision:
                    raise ValueError("keymap coordinator precondition changed")
                if hashlib.sha256(self.runtime_path.read_bytes()).hexdigest() != message.get("expected_sha256"):
                    raise ValueError("persisted keymap digest changed")
                await self._owner_state()
                fields = ("operation_id", "expected_owner_epoch", "expected_keymap_revision", "expected_layer_revision", "row", "col", "expected_action", "hold_ms", "expected_output_revision")
                try:
                    return await self.native_request({"t": "guarded_tap", **{key: message[key] for key in fields if key in message}})
                except Exception as exc:
                    if isinstance(getattr(exc, "owner_response", None), dict):
                        return exc.owner_response
                    # Transport loss can follow a committed press. Resolve this
                    # exact operation, never convert uncertainty into rejection.
                    try:
                        outcome = await asyncio.wait_for(self.native_request({"t": "operation_status", "operation_id": message["operation_id"]}), timeout=2.0)
                        return outcome.get("operation", outcome)
                    except Exception:
                        return {"result": "unknown", "operation_id": message["operation_id"], "state": "unknown", "executed": None}
            except Exception as exc:
                return {"t": kind, "result": "error", "msg": str(exc), **self.snapshot()}

    async def _owner_state(self):
        state = await asyncio.wait_for(self.native_request({"t": "owner_state", "include_keymap": True}), timeout=2.0)
        if state.get("result") != "ok" or state.get("layers") != self.layers.layers_snapshot():
            raise RuntimeError("native and companion keymap mismatch")
        if (not isinstance(state.get("owner_epoch"), str) or not state["owner_epoch"]
            or any(type(state.get(key)) is not int or state[key] < 0 for key in ("keymap_revision", "layer_revision"))):
            raise RuntimeError("native owner metadata unavailable or invalid")
        return state

    async def _apply(self, candidate, operation_id, expected_owner=None):
        if self.native_request is not None:
            before = await self._owner_state()
            if expected_owner is not None and any(before.get(key) != expected_owner.get(key) for key in ("owner_epoch", "keymap_revision")):
                raise ValueError("keymap owner precondition changed")
            request = {"t": "apply_keymap", "layers": candidate,
                       "expected_owner_epoch": before["owner_epoch"],
                       "expected_keymap_revision": before["keymap_revision"], "operation_id": operation_id}
            expected_revision = before["keymap_revision"] + int(candidate != before["layers"])
            def confirmed(ack):
                return (isinstance(ack, dict) and ack.get("result") == "ok"
                    and ack.get("operation_id") == operation_id
                    and ack.get("owner_epoch") == before["owner_epoch"]
                    and type(ack.get("keymap_revision")) is int
                    and ack.get("keymap_revision") == expected_revision
                    and type(ack.get("layer_revision")) is int
                    and ack["layer_revision"] >= before["layer_revision"]
                    and ack.get("runtime_applied") is True)
            ack = None
            try:
                ack = await asyncio.wait_for(self.native_request(request), timeout=2.0)
            except Exception as exc:
                ack = getattr(exc, "owner_response", None)
            if isinstance(ack, dict) and ack.get("result") == "error":
                raise RuntimeError(f"native keymap rejected: {ack.get('error')}")
            if not confirmed(ack):
                # The operation may already have committed. Query it; never replay the mutation.
                try:
                    ack = await asyncio.wait_for(self.native_request({"t": "operation_status", "operation_id": operation_id}), timeout=2.0)
                    if isinstance(ack.get("operation"), dict):
                        ack = ack["operation"]
                except Exception as exc:
                    raise UnknownOwnerOutcome("native keymap apply outcome unknown; do not replay") from exc
                if not confirmed(ack):
                    raise UnknownOwnerOutcome("native keymap operation outcome unknown; do not replay")
            self.owner_ack = {key: ack[key] for key in ("owner_epoch", "keymap_revision", "layer_revision") if key in ack}
        else:
            self.owner_ack = {"owner_epoch": self.owner_epoch, "keymap_revision": self.revision + 1}
        self.layers.replace_layers(candidate)
        self.revision += 1

    async def execute(self, message):
        async with self.lock:
            t = message.get("t")
            response = {"t": t, "result": "error", "runtime_applied": False, "persisted": False}
            operation_id = str(message.get("operation_id") or uuid.uuid4().hex)
            if operation_id in self.operations:
                previous, outcome = self.operations[operation_id]
                return dict(outcome) if previous == message else {**response, "msg": "operation_id conflict"}
            response["operation_id"] = operation_id
            try:
                candidate = self.layers.layers_snapshot()
                scratch = LayerManager()
                scratch.load(candidate)
                if t == "KEYMAP_COMPARE_APPLY":
                    if message.get("expected_coordinator_epoch") != self.owner_epoch or message.get("expected_runtime_revision") != self.revision:
                        raise ValueError("keymap coordinator precondition changed")
                    if self.revision != self.persisted_revision:
                        raise ValueError("keymap has unpersisted changes")
                    if self.runtime_path.stat().st_size > 2 * 1024 * 1024:
                        raise ValueError("keymap file exceeds limit")
                    if hashlib.sha256(self.runtime_path.read_bytes()).hexdigest() != message.get("expected_sha256"):
                        raise ValueError("persisted keymap digest changed")
                if t in {"M", "KEYMAP_COMPARE_APPLY"}:
                    layer, row, col = (int(message[k]) for k in ("l", "r", "c"))
                    action = message["a"]
                    if not 0 <= layer < 32 or not self.matrix_in_range(row, col):
                        raise ValueError("keymap position out of range")
                    if not isinstance(action, str) or not action or action == "None":
                        raise ValueError("action must be a non-empty string")
                    scratch.set_action(layer, row, col, action)
                elif t == "LAYER_ADD":
                    response["layer"] = scratch.add_layer()
                elif t == "LAYER_CLEAR":
                    layer = int(message["l"])
                    if not 0 <= layer < 32:
                        raise ValueError("layer out of range")
                    response["operation"], response["keys"] = scratch.clear_layer(layer)
                    response["layer"] = layer
                elif t == "RESET_KEYMAP":
                    candidate = keymap_json_to_layers(json.loads(self.default_path.read_text(encoding="utf-8")))
                    if not candidate:
                        raise ValueError("default keymap has no layers")
                    scratch.load(candidate)
                elif t != "S":
                    raise ValueError("unknown keymap mutation")
                if t != "S":
                    candidate = scratch.layers_snapshot()
                    await self._apply(candidate, operation_id, message.get("expected_owner"))
                elif self.native_request is not None:
                    owner = await self._owner_state()
                    if self.owner_ack is not None and any(owner.get(key) != self.owner_ack.get(key) for key in ("owner_epoch", "keymap_revision")):
                        raise RuntimeError("keymap owner changed before save")
                    self.owner_ack = {key: owner[key] for key in ("owner_epoch", "keymap_revision", "layer_revision")}
                response["runtime_applied"] = True
                if t != "M":
                    if t == "RESET_KEYMAP":
                        removed = self.runtime_path.exists()
                        self.runtime_path.unlink(missing_ok=True)
                        response.update(removed_runtime=removed, default_path=str(self.default_path), runtime_path=str(self.runtime_path))
                    else:
                        response["path"] = save_runtime_keymap(candidate, preferred=str(self.runtime_path), fallback=str(self.default_path))
                    self.persisted_revision = self.revision
                response.update(self.snapshot(), result="ok", layers=len(candidate))
            except Exception as exc:
                response.update(self.snapshot(), result="error", msg=str(exc))
                if isinstance(exc, UnknownOwnerOutcome):
                    response.update(runtime_applied=None, owner_outcome="unknown", persisted=False)
            if len(self.operations) >= 128:
                self.operations.pop(next(iter(self.operations)))
            self.operations[operation_id] = (dict(message), dict(response))
            return response
