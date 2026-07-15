#!/usr/bin/env python3
"""Local smoke test for push-trigger LED Life Game helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.life_game import LedLifeGameState, cells_from_led_positions  # noqa: E402
from vialrgb_effects import VIALRGB_EFFECTS, VIALRGB_PREVIEW_GROUPS, VIALRGB_RENDER_GROUPS  # noqa: E402


def main() -> None:
    positions = {
        f"{row},{col}": {"x": col * 10.0, "y": row * 10.0}
        for row in range(3)
        for col in range(3)
    }
    keys = list(positions)
    cells = cells_from_led_positions(keys, positions)
    assert len(cells) == 9
    assert {cell.x for cell in cells} == {0, 1, 2}
    assert {cell.y for cell in cells} == {0, 1, 2}

    state = LedLifeGameState(cells)
    center_idx = keys.index("1,1")
    state.seed_index(center_idx, radius=1)
    first_frame = state.frame(len(keys))
    assert sum(1 for value in first_frame if value > 0) == 9
    assert state.alive_count == 9
    assert state.tick_count == 0

    state.step()
    second_frame = state.frame(len(keys))
    assert state.tick_count == 1
    assert state.alive_count == 4
    assert sum(1 for value in second_frame if value >= 1.0) == 4
    assert sum(1 for value in second_frame if 0 < value < 1.0) == 0
    second_transitions = state.transition_frame(len(keys))
    assert sum(1 for marker in second_transitions if marker == "dying") == 5

    state.clear()
    assert state.alive_count == 0
    assert state.tick_count == 0
    assert not any(state.frame(len(keys)))

    state.queue_seed_index(keys.index("1,1"), radius=0)
    assert state.alive_count == 0
    assert state.transition_frame(len(keys))[keys.index("1,1")] == "pending"
    assert state.frame(len(keys))[keys.index("1,1")] == 1.0
    state.step()
    assert state.alive_count == 1
    assert state.transition_frame(len(keys))[keys.index("1,1")] == "born"
    state.step()
    assert state.transition_frame(len(keys))[keys.index("1,1")] == "dying"
    state.clear()

    state.seed_index(keys.index("1,1"), radius=0)
    state.step()
    transitions = state.transition_frame(len(keys))
    transition_values = state.transition_intensity_frame(len(keys))
    assert transitions[keys.index("1,1")] == "dying"
    assert transition_values[keys.index("1,1")] == 1.0
    assert state.frame(len(keys))[keys.index("1,1")] == 0.0
    state.step()
    transitions = state.transition_frame(len(keys))
    transition_values = state.transition_intensity_frame(len(keys))
    assert transitions[keys.index("1,1")] == ""
    assert transition_values[keys.index("1,1")] == 0.0
    assert state.frame(len(keys))[keys.index("1,1")] == 0.0
    state.step()
    transitions = state.transition_frame(len(keys))
    transition_values = state.transition_intensity_frame(len(keys))
    assert state.transition_frame(len(keys))[keys.index("1,1")] == ""
    assert state.frame(len(keys))[keys.index("1,1")] == 0.0

    state.clear()
    for key in ("1,0", "1,1", "1,2"):
        state.seed_index(keys.index(key), radius=0)
    state.step()
    transitions = state.transition_frame(len(keys))
    transition_values = state.transition_intensity_frame(len(keys))
    assert transitions[keys.index("1,0")] == "dying"
    assert transition_values[keys.index("1,0")] == 1.0
    assert transitions[keys.index("1,1")] == "birth_parent"
    assert transitions[keys.index("1,2")] == "dying"
    assert transitions[keys.index("0,1")] == "born"
    assert transitions[keys.index("2,1")] == "born"
    assert state.alive_count == 3

    staggered_positions = {
        "0,0": {"x": 0.0, "y": 0.0},
        "0,1": {"x": 10.0, "y": 0.0},
        "0,2": {"x": 20.0, "y": 0.0},
        "0,3": {"x": 30.0, "y": 0.0},
        "0,4": {"x": 40.0, "y": 0.0},
        "1,0": {"x": 5.0, "y": 10.0},
        "1,1": {"x": 15.0, "y": 10.0},
        "1,2": {"x": 25.0, "y": 10.0},
        "1,3": {"x": 35.0, "y": 10.0},
        "1,4": {"x": 45.0, "y": 10.0},
    }
    staggered_keys = list(staggered_positions)
    staggered = LedLifeGameState(cells_from_led_positions(staggered_keys, staggered_positions))
    staggered.seed_index(staggered_keys.index("1,2"), radius=1)
    staggered_frame = staggered.frame(len(staggered_keys))
    lit_keys = {staggered_keys[idx] for idx, value in enumerate(staggered_frame) if value > 0}
    assert {"0,2", "0,3", "1,1", "1,2", "1,3"} <= lit_keys
    assert "0,1" not in lit_keys
    assert "0,0" not in lit_keys
    assert "0,4" not in lit_keys

    assert VIALRGB_EFFECTS[1001] == "LED Life Game"
    assert 1001 in VIALRGB_PREVIEW_GROUPS["experimental"]
    assert VIALRGB_RENDER_GROUPS["life_game"] == {1001}
    print("ok: LED Life Game effect helpers")


if __name__ == "__main__":
    main()
