#!/usr/bin/env python3
"""Static checks for SequenceEngine design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    design = (ROOT / "docs" / "feature" / "sequence-engine-design.md").read_text(encoding="utf-8")
    backlog = (ROOT / "docs" / "feature/design-todo-backlog.md").read_text(encoding="utf-8")
    feature_readme = (ROOT / "docs" / "feature" / "README.md").read_text(encoding="utf-8")
    status_path = ROOT / "docs" / "CURRENT_STATUS.md"
    status = status_path.read_text(encoding="utf-8") if status_path.is_file() else None
    inventory = (ROOT / "docs" / "ops" / "test-script-inventory.md").read_text(encoding="utf-8")
    primitives = (ROOT / "daemon" / "logicd" / "sequence_engine.py").read_text(encoding="utf-8")
    morse_adapter = (ROOT / "daemon" / "logicd" / "sequence_morse.py").read_text(encoding="utf-8")

    required_design_phrases = [
        "SequenceEngine",
        "SequenceEmission",
        "`MORSE(name)`",
        "`TD(name)`",
        "`LT` / `MT` / `TT`",
        "Tap Dance",
        "Tap-Hold",
        "`tap(action)`",
        "`press(action)`",
        "`release(action)`",
        "`suppress(action)`",
        "`restore(action)`",
        "`feedback(event)`",
        "MORSE_FEEDBACK",
        "behavior change なし",
        "Combo を SequenceEngine に入れるか",
        "Caps Word / Repeat Key",
        "stale timeout",
        "related feature fit",
        "Key Override",
        "emission layer 候補",
        "Leader",
        "profile 候補",
        "Dynamic Macro record",
        "final-action observer 候補",
        "Key Toggle / Key Lock / Drag Lock",
        "synthetic source 候補",
        "Mod-Morph / Grave Escape",
        "stateless resolver",
        "blocking issues before implementation",
        "Press / release owner",
        "Suppress / restore accounting",
        "Timer generation and cancel",
        "Resolver / transformer boundary",
        "Feedback separation",
        "Compatibility and migration blast radius",
        "reference count",
        "MORSE_FEEDBACK",
    ]
    for phrase in required_design_phrases:
        assert phrase in design, phrase

    assert "[feature/sequence-engine-design.md](sequence-engine-design.md)" in backlog
    assert "Sequence engine / timed interaction unification design" in backlog
    assert "press / release owner を固定" in backlog
    assert "suppress / restore accounting を固定" in backlog
    assert "feedback separation を固定" in backlog
    assert "compatibility guard を固定" in backlog
    if status is not None:
        assert "SequenceEngine timed interaction safety boundary" in status
    assert "SequencePressedAction" in primitives
    assert "SequenceSuppressionLedger" in primitives
    assert "SequenceTimerRegistry" in primitives
    assert "split_host_and_feedback" in primitives
    assert "[sequence-engine-design.md](sequence-engine-design.md)" in feature_readme
    assert "script/test_sequence_engine_design_doc.py" in inventory
    assert "script/test_sequence_engine_primitives.py" in inventory
    assert "script/test_sequence_engine_compatibility_guard.py" in inventory
    assert "script/test_sequence_morse_profile.py" in inventory
    assert "class SequenceEmission" in primitives
    assert "class SequenceProfile" in primitives
    assert "class SequenceTimerRef" in primitives
    assert "class SequenceResult" in primitives
    assert "HOST_EMISSION_KINDS" in primitives
    assert "NON_HOST_EMISSION_KINDS" in primitives
    assert "class MorseSequenceProfile" in morse_adapter
    assert "MorseBehaviorRuntime" in morse_adapter

    print("ok: SequenceEngine design documentation is linked and guarded")


if __name__ == "__main__":
    main()
