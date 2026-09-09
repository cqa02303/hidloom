#!/usr/bin/env python3
"""Keymap owner ACK and persistence ordering with isolated files and fake IPC."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT)]
from logicd.keymap import LayerManager
from logicd.keymap_coordinator import KeymapCoordinator


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        default, runtime = root / "default.json", root / "runtime.json"
        template = {"layers": [{"0,0": "KC_A"}], "metadata": "preserved"}
        # Existing keymap serialization helper is used, independent of native candidate format.
        from logicd.config_loader import layers_to_keymap_json
        default.write_text(json.dumps(layers_to_keymap_json(template["layers"], {"_layout_def": {"matrix": [[0, 0], [0, 1], [1, 0], [1, 1]]}})))
        layers = LayerManager()
        layers.load(template["layers"])
        owner = {"owner_epoch": "owner-1", "keymap_revision": 1, "layer_revision": 0, "layers": template["layers"], "result": "ok"}
        calls = []
        offline = False
        async def request(payload):
            calls.append(payload)
            if offline:
                raise ConnectionError("fixture owner offline")
            if payload["t"] == "owner_state":
                return dict(owner)
            assert payload["t"] == "apply_keymap"
            assert payload["expected_owner_epoch"] == owner["owner_epoch"]
            assert payload["expected_keymap_revision"] == owner["keymap_revision"]
            owner.update(layers=payload["layers"], keymap_revision=owner["keymap_revision"] + 1)
            return {**owner, "operation_id": payload["operation_id"], "runtime_applied": True}
        coordinator = KeymapCoordinator(layers, runtime, default, lambda r,c: 0 <= r < 2 and 0 <= c < 2, native_request=request)
        changed = await coordinator.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_B"})
        assert changed["result"] == "ok" and changed["runtime_applied"]
        assert changed["persisted"] is False and not runtime.exists()
        assert owner["layers"][0]["0,0"] == "KC_B"
        assert layers.get_action(0, 0) == "KC_B"
        saved = await coordinator.execute({"t": "S"})
        assert saved["persisted"] and saved["result"] == "ok"
        assert len([c for c in calls if c["t"] == "apply_keymap"]) == 1, "S must not reload/clear held state"
        added = await coordinator.execute({"t": "LAYER_ADD"})
        assert added["result"] == "ok" and len(owner["layers"]) == 2
        cleared = await coordinator.execute({"t": "LAYER_CLEAR", "l": 1})
        assert cleared["result"] == "ok" and len(owner["layers"]) == 1
        reset = await coordinator.execute({"t": "RESET_KEYMAP"})
        assert reset["result"] == "ok" and owner["layers"][0]["0,0"] == "KC_A"
        offline = True
        failed = await coordinator.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_C"})
        assert failed["result"] == "error" and not failed["runtime_applied"]
        assert layers.get_action(0, 0) == "KC_A"
        # Standalone owner preserves active layer and original press mapping across apply.
        layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}])
        layers.on_press("MO(1)")
        standalone = KeymapCoordinator(layers, runtime, default, lambda r,c: True)
        await standalone.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_D"})
        assert layers.active_snapshot()["momentary"] == [1]
    await test_ack_outcomes()
    print("keymap coordinator: ok")


async def test_ack_outcomes():
    """A sent mutation is resolved by its identity, never replayed after ACK loss."""
    async def run_case(name, *, truncated=False, query_lost=False, corrupt=None, action="KC_B"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layers = LayerManager()
            layers.load([{"0,0": "KC_A"}])
            owner = {"result": "ok", "owner_epoch": "ack-owner", "keymap_revision": 1,
                     "layer_revision": 0, "layers": [{"0,0": "KC_A"}]}
            calls = []
            retained = None

            async def request(payload):
                nonlocal retained
                calls.append(dict(payload))
                if payload["t"] == "owner_state":
                    return dict(owner)
                if payload["t"] == "operation_status":
                    assert payload["operation_id"] == retained["operation_id"], name
                    if query_lost:
                        raise ConnectionError("fixture outcome query lost")
                    return dict(retained)
                assert payload["t"] == "apply_keymap", (name, payload)
                revision = owner["keymap_revision"] + int(payload["layers"] != owner["layers"])
                retained = {"result": "ok", "operation_id": payload["operation_id"],
                            "owner_epoch": owner["owner_epoch"], "keymap_revision": revision,
                            "layer_revision": owner["layer_revision"], "runtime_applied": True}
                if corrupt is None:
                    owner.update(layers=payload["layers"], keymap_revision=revision)
                else:
                    # The companion must not trust a superficially successful ACK
                    # when this owner has not applied the requested candidate.
                    field, value = corrupt
                    if value is None:
                        retained.pop(field)
                    else:
                        retained[field] = value
                if truncated:
                    raise json.JSONDecodeError("fixture truncated ACK after apply", "{", 1)
                return dict(retained)

            coordinator = KeymapCoordinator(layers, root / "runtime.json", root / "default.json",
                                            lambda row, col: row == 0 and col == 0, native_request=request)
            message = {"t": "M", "l": 0, "r": 0, "c": 0, "a": action, "operation_id": name}
            result = await coordinator.execute(message)
            assert sum(call["t"] == "apply_keymap" for call in calls) == 1, (name, calls)
            queries = [call for call in calls if call["t"] == "operation_status"]
            assert len(queries) == int(truncated or corrupt is not None), (name, calls)
            assert all(call["operation_id"] == name for call in queries), (name, queries)
            assert not (root / "runtime.json").exists(), name
            assert result["persisted"] is False, (name, result)
            if query_lost or corrupt is not None:
                assert result["result"] == "error" and result["runtime_applied"] is None, (name, result)
                assert result["owner_outcome"] == "unknown", (name, result)
                assert layers.get_action(0, 0) == "KC_A", (name, result)
                assert owner["layers"][0]["0,0"] == (action if truncated else "KC_A"), name
            else:
                assert result["result"] == "ok" and result["runtime_applied"] is True, (name, result)
                assert layers.get_action(0, 0) == action == owner["layers"][0]["0,0"], name
                assert result["owner"]["keymap_revision"] == (1 if action == "KC_A" else 2), (name, result)
            # Repeating the same request returns the recorded outcome without
            # creating a second native operation, including an unknown outcome.
            count = len(calls)
            assert await coordinator.execute(message) == result, name
            assert len(calls) == count, (name, calls)

    await run_case("truncated-ack-resolved", truncated=True)
    await run_case("truncated-ack-query-lost", truncated=True, query_lost=True)
    for name, field, value in (
        ("wrong-epoch", "owner_epoch", "different-owner"),
        ("missing-epoch", "owner_epoch", None),
        ("wrong-revision", "keymap_revision", 1),
        ("float-revision", "keymap_revision", 2.0),
        ("missing-revision", "keymap_revision", None),
        ("missing-layer-revision", "layer_revision", None),
        ("false-runtime-applied", "runtime_applied", False),
        ("missing-runtime-applied", "runtime_applied", None),
    ):
        await run_case(name, corrupt=(field, value))
    await run_case("no-op-retains-native-revision", action="KC_A")

    # Invalid preconditions must be rejected before the owner sees a mutation.
    for field, value in (
        ("owner_epoch", None), ("owner_epoch", ""), ("owner_epoch", 1),
        ("keymap_revision", None), ("keymap_revision", True),
        ("keymap_revision", 1.0), ("keymap_revision", -1),
        ("layer_revision", None), ("layer_revision", False),
        ("layer_revision", 0.0), ("layer_revision", -1),
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layers = LayerManager()
            layers.load([{"0,0": "KC_A"}])
            owner = {"result": "ok", "owner_epoch": "valid-owner", "keymap_revision": 1,
                     "layer_revision": 0, "layers": layers.layers_snapshot()}
            if value is None:
                owner.pop(field)
            else:
                owner[field] = value
            calls = []

            async def invalid_owner(payload):
                calls.append(dict(payload))
                assert payload["t"] == "owner_state", (field, value, payload)
                return dict(owner)

            coordinator = KeymapCoordinator(layers, root / "runtime.json", root / "default.json",
                                            lambda *_: True, native_request=invalid_owner)
            result = await coordinator.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_B"})
            assert result["result"] == "error" and result["runtime_applied"] is False, (field, value, result)
            assert [call["t"] for call in calls] == ["owner_state"], (field, value, calls)
            assert layers.get_action(0, 0) == "KC_A" and not (root / "runtime.json").exists()


if __name__ == "__main__":
    asyncio.run(main())
