#!/usr/bin/env python3
"""Press-time action ownership for overlapping synthetic and physical sources."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT)]
from logicd.keymap import LayerManager
from logicd.interaction_engine import InteractionEngine


def main():
    layers = LayerManager()
    layers.load([{"0,0": "KC_A", "0,1": "LT(1,KC_B)"}, {"0,0": "KC_C"}])
    engine = InteractionEngine(layers)
    first = engine.on_key(0,0,True,0.0,owner="web-1")
    assert [(e.action,e.owner) for e in first] == [("KC_A","web-1")]
    assert engine.on_key(0,0,True,0.01,owner="web-1") == []
    layers.momentary_on(1)
    second = engine.on_key(0,0,True,0.02,owner="web-2")
    assert [(e.action,e.owner) for e in second] == [("KC_C","web-2")]
    layers.momentary_off(1)
    assert [(e.action,e.owner) for e in engine.on_key(0,0,False,0.03,owner="web-1")] == [("KC_A","web-1")]
    assert len(engine.pressed) == 1
    assert [(e.action,e.owner) for e in engine.on_key(0,0,False,0.04,owner="web-2")] == [("KC_C","web-2")]
    assert engine.on_key(0,0,False,0.05,owner="web-2") == []
    assert engine.on_key(0,1,True,1.0,owner="web-1") == []
    tick = engine.on_tick(1.3)
    assert [(e.action,e.owner) for e in tick] == [("MO(1)","web-1")]
    released = engine.on_key(0,1,False,1.4,owner="web-1")
    assert [(e.action,e.owner) for e in released] == [("MO(1)","web-1")]
    print("interaction source identity: ok")


if __name__ == "__main__":
    main()
