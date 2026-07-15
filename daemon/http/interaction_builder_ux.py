"""Read-only UX metadata for Interaction builders.

The Interaction tab contains builders for Combo, Tap Dance, Key Override, and
Timing. This helper centralizes labels, short descriptions, and source-key
selection policy without coupling presentation to save semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import web

INTERACTION_BUILDER_UX_ROUTE = "/api/interaction/builder-ux"


@dataclass(frozen=True)
class InteractionBuilderUxSpec:
    """Small UI description for one Interaction builder."""

    key: str
    title: str
    subtitle: str
    source_policy: str
    save_scope: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "subtitle": self.subtitle,
            "source_policy": self.source_policy,
            "save_scope": self.save_scope,
            "warnings": list(self.warnings),
        }


_BUILDER_SPECS = (
    InteractionBuilderUxSpec(
        key="combo",
        title="Combo builder",
        subtitle="複数の物理キーを同時押しした時に、1つの action を出します。",
        source_policy="Prefer selecting source keys from the rendered keymap; row/col numeric input remains a fallback.",
        save_scope="settings.interaction.combos[]",
        warnings=(
            "source key は keycode ではなく物理 matrix position として保存する",
            "同じ source key を複数 combo で共有すると誤爆しやすい",
        ),
    ),
    InteractionBuilderUxSpec(
        key="tap_dance",
        title="Tap Dance builder",
        subtitle="同じ物理キーの tap 回数で action を切り替えます。",
        source_policy="Source key assignment stays in keymap; builder edits the TD(name) definition only.",
        save_scope="settings.interaction.tap_dances{}",
        warnings=(
            "keymap 側には TD(name) を割り当てる必要がある",
            "tap term が短すぎると通常 tap と区別しづらい",
        ),
    ),
    InteractionBuilderUxSpec(
        key="key_override",
        title="Key Override builder",
        subtitle="指定 modifier / trigger が押されている時だけ、対象 key の action を置き換えます。",
        source_policy="Use the Action picker for trigger/key/replacement; matrix position is not stored here.",
        save_scope="settings.interaction.key_overrides[]",
        warnings=(
            "trigger と key は action 名であり、row/col ではない",
            "Mod-Morph と同じ key にかかる場合は priority warning を確認する",
        ),
    ),
    InteractionBuilderUxSpec(
        key="timing",
        title="Advanced Timing",
        subtitle="Tap-hold / combo / tap dance の判定時間をまとめて調整します。",
        source_policy="No source key selection; these are global timing knobs.",
        save_scope="settings.interaction timing fields",
        warnings=(
            "小さすぎる値は実機で取りこぼしやすい",
            "大きすぎる値は入力遅延として体感される",
        ),
    ),
)


def interaction_builder_ux_specs() -> dict[str, dict[str, Any]]:
    """Return builder UX metadata keyed by builder name."""
    return {spec.key: spec.to_dict() for spec in _BUILDER_SPECS}


def interaction_builder_ux_payload() -> dict[str, Any]:
    """Return a read-only payload usable by the Interaction tab."""
    return {
        "result": "ok",
        "schema": "interaction.builder_ux.v1",
        "route": INTERACTION_BUILDER_UX_ROUTE,
        "read_only": True,
        "builders": interaction_builder_ux_specs(),
        "selection_modes": {
            "matrix_position": {
                "label": "Keymap position",
                "description": "Rendered keymap から row/col を選ぶ。Combo の source key で優先する。",
            },
            "action_picker": {
                "label": "Action picker",
                "description": "QMK/Vial action 名を選ぶ。Tap Dance action や Key Override で使う。",
            },
        },
        "polish_status": {
            "schema": "interaction.builder_ux.polish.v1",
            "status": "first_slice_complete",
            "tap_dance": {
                "editor_scope": "definition_only",
                "assignment_action": "TD(name)",
                "copy_action": True,
                "rename_updates_existing_definition": True,
                "source_key_assignment": "keymap_remap_flow",
            },
            "key_override": {
                "editor_scope": "action_names_only",
                "source_key_assignment": "not_matrix_position",
                "trigger_input": "comma_separated_actions",
                "replacement_picker": True,
            },
            "warning_display": {
                "summary_metric": "Inspector warnings count",
                "builder_inline": "warnings from read-only inspector rows",
                "accordion_badge": "Warn N",
                "dedupe_rule": "metadata helper text explains editor scope; inspector warnings carry validation issues",
            },
            "next_local_todo": "runtime_feedback_or_real_device_touch_flick",
        },
        "non_goals": [
            "builder helper は設定を保存しない",
            "source key selection は keycode ではなく matrix position と action picker を分けて扱う",
            "実機打鍵の良し悪しは inspector warning と実機確認へ分ける",
        ],
    }


def builder_subtitle(builder_key: str) -> str:
    """Return a short subtitle for a builder key."""
    spec = interaction_builder_ux_specs().get(builder_key)
    return "" if spec is None else str(spec["subtitle"])


async def interaction_builder_ux_response() -> web.Response:
    """Return read-only builder UX metadata for the Interaction tab."""
    return web.json_response(interaction_builder_ux_payload())


def register_interaction_builder_ux_route(app: web.Application) -> None:
    """Register the read-only Interaction builder UX metadata route."""

    async def handle_interaction_builder_ux(_request: web.Request) -> web.Response:
        return await interaction_builder_ux_response()

    app.router.add_get(INTERACTION_BUILDER_UX_ROUTE, handle_interaction_builder_ux)
