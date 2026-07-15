"use strict";

// Layer add / clear controls for the keymap editor.  Layer numbers are stable:
// clearing a layer writes KC_TRNS across the layer instead of removing and
// renumbering following layers.

async function _callLayerApi(url, method) {
  const resp = await csrfFetch(url, { method });
  const data = await resp.json();
  if (!resp.ok || data.result !== "ok") {
    throw new Error(data.msg || `HTTP ${resp.status}`);
  }
  return data;
}

function _setLayerControlBusy(busy) {
  for (const id of ["layer-add-btn", "layer-clear-btn"]) {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = busy;
  }
}

async function addRuntimeLayer() {
  _setLayerControlBusy(true);
  try {
    const result = await _callLayerApi("/api/keymap/layers", "POST");
    const nextLayer = Number.parseInt(result.layer, 10);

    await refreshLayoutLayers();
    if (Number.isFinite(nextLayer)) _remapLayer = nextLayer;
    _updateLayerSelector();
    updateKeyboardLayerDisplay(_remapLayer);
    updateRemapTargetForCurrentLayer();
    showToast(`Layer ${nextLayer} を追加しました`);
  } catch (e) {
    showToast(`Layer追加エラー: ${e.message}`, true);
  } finally {
    _setLayerControlBusy(false);
  }
}

async function clearCurrentLayer() {
  const layer = Number.parseInt(_remapLayer, 10);
  if (!Number.isFinite(layer) || layer <= 0) {
    showToast("Layer 0 は削除できません", true);
    return;
  }

  const ok = window.confirm(
    `Layer ${layer} を削除相当として全キー KC_TRNS に戻します。\n` +
    "layer 番号は詰めません。よろしいですか？"
  );
  if (!ok) return;

  _setLayerControlBusy(true);
  try {
    const result = await _callLayerApi(`/api/keymap/layers/${layer}`, "DELETE");

    await refreshLayoutLayers();
    if (result.operation === "removed") {
      _remapLayer = Math.max(0, _allLayers.length - 1);
    } else {
      _remapLayer = Math.min(layer, Math.max(0, _allLayers.length - 1));
    }
    _updateLayerSelector();
    updateKeyboardLayerDisplay(_remapLayer);
    updateRemapTargetForCurrentLayer();
    showToast(
      result.operation === "removed"
        ? `Layer ${layer} を削除しました`
        : `Layer ${layer} を KC_TRNS に初期化しました`
    );
  } catch (e) {
    showToast(`Layer削除エラー: ${e.message}`, true);
  } finally {
    _setLayerControlBusy(false);
  }
}
