#!/usr/bin/env python3
"""Regression tests for http.interaction_inspector_summary."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from interaction_inspector_summary import (  # noqa: E402
    attach_interaction_validation_summary,
    build_interaction_validation_summary,
    section_status,
    severity_counts,
)


def sample_payload():
    return {
        "result": "ok",
        "sections": {
            "combos": [
                {
                    "status": "warning",
                    "warnings": [
                        {"severity": "warning", "message": "shared key", "source": "settings.interaction.combos[0]"},
                    ],
                }
            ],
            "tap_dances": [
                {"status": "ok", "warnings": []},
            ],
            "key_overrides": [
                {
                    "status": "error",
                    "warnings": [
                        {"severity": "error", "message": "missing replacement", "source": "settings.interaction.key_overrides[0]"},
                    ],
                }
            ],
        },
        "warnings": [
            {"severity": "warning", "message": "shared key", "source": "settings.interaction.combos[0]"},
            {"severity": "error", "message": "missing replacement", "source": "settings.interaction.key_overrides[0]"},
            {"severity": "info", "message": "term needs tuning", "source": "settings.interaction.tap_dances.foo"},
            {"severity": "unknown", "message": "old warning shape", "source": "settings.interaction"},
        ],
    }


def test_severity_counts_normalizes_unknown_to_warning() -> None:
    counts = severity_counts(sample_payload()["warnings"])
    assert counts == {"error": 1, "warning": 2, "info": 1}


def test_section_status_aggregates_worst_status() -> None:
    assert section_status([]) == "ok"
    assert section_status([{"status": "ok"}]) == "ok"
    assert section_status([{"status": "ok"}, {"status": "warning"}]) == "warning"
    assert section_status([{"status": "warning"}, {"status": "error"}]) == "error"


def test_validation_summary_builds_save_hint_and_sections() -> None:
    summary = build_interaction_validation_summary(sample_payload())

    assert summary["schema"] == "interaction.inspector.validation_summary.v1"
    assert summary["read_only"] is True
    assert summary["severity_counts"] == {"error": 1, "warning": 2, "info": 1}
    assert summary["total_warnings"] == 4
    assert summary["has_errors"] is True
    assert summary["has_warnings"] is True
    assert summary["save_hint"] == "blocked"
    assert summary["sections"]["combos"] == {"items": 1, "status": "warning", "warnings": 1}
    assert summary["sections"]["tap_dances"] == {"items": 1, "status": "ok", "warnings": 0}
    assert summary["sections"]["key_overrides"] == {"items": 1, "status": "error", "warnings": 1}


def test_save_hint_review_and_ok() -> None:
    review = build_interaction_validation_summary({"sections": {}, "warnings": [{"severity": "warning"}]})
    assert review["save_hint"] == "review"

    ok = build_interaction_validation_summary({"sections": {}, "warnings": []})
    assert ok["save_hint"] == "ok"


def test_attach_summary_does_not_mutate_original_payload() -> None:
    payload = sample_payload()
    result = attach_interaction_validation_summary(payload)

    assert "validation_summary" not in payload
    assert result["validation_summary"]["save_hint"] == "blocked"
    assert result["sections"] is payload["sections"]


def main() -> None:
    test_severity_counts_normalizes_unknown_to_warning()
    test_section_status_aggregates_worst_status()
    test_validation_summary_builds_save_hint_and_sections()
    test_save_hint_review_and_ok()
    test_attach_summary_does_not_mutate_original_payload()
    print("ok: interaction inspector validation summary is read-only and stable")


if __name__ == "__main__":
    main()
