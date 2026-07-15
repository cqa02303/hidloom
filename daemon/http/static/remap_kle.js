"use strict";

// keyboard-layout-editor.com preview for the current remap layer.

function _kleLabelForVialEncoderSlot(slot, item) {
  const encoderLegend = getVialEncoderLegend(slot?.label || item);
  if (!encoderLegend) return null;

  const matrixKey = slot.matrix ? `${slot.matrix.row},${slot.matrix.col}` : null;
  const keycode = matrixKey ? layerKeycodeForMatrix(matrixKey, _remapLayer) : "";
  const actionLabel = keycodeDisplayLabel(keycode, _labelsCache, "");
  const parts = String(item).split("\n");
  while (parts.length < 10) parts.push("");
  parts[0] = `${encoderLegend.index},${encoderLegend.action}`;
  if (actionLabel) parts[1] = actionLabel;
  parts[parts.length - 1] = "e";
  return parts.join("\n");
}

function _cloneKleLayoutWithCurrentLayerLabels() {
  let slotIndex = 0;
  return (_kleLayoutSource || []).map(row => {
    if (!Array.isArray(row)) return row;
    return row.map(item => {
      if (typeof item !== "string") {
        return item && typeof item === "object" ? { ...item } : item;
      }

      const slot = _keyboardSlots[slotIndex++];
      if (!slot) return item;
      const encoderLabel = _kleLabelForVialEncoderSlot(slot, item);
      if (encoderLabel) return encoderLabel;

      const matrixKey = slot.matrix ? `${slot.matrix.row},${slot.matrix.col}` : null;
      const keycode = matrixKey ? layerKeycodeForMatrix(matrixKey, _remapLayer) : "";
      return keycodeDisplayLabel(
        keycode,
        _labelsCache,
        displayFallbackLabel(slot, keycode),
      );
    });
  });
}

function openKleForCurrentLayer() {
  if (!_kleLayoutSource || _kleLayoutSource.length === 0) {
    showToast("KLEレイアウト情報がありません", true);
    return;
  }

  const kleLayout = _cloneKleLayoutWithCurrentLayerLabels();
  const rawData = JSON.stringify(kleLayout);
  const url = `https://www.keyboard-layout-editor.com/##${encodeURIComponent(rawData)}`;
  const win = window.open(url, "_blank");
  if (!win) {
    showToast("ポップアップがブロックされました", true);
    return;
  }
  win.opener = null;
  showToast(`KLEでLayer ${_remapLayer}を開きました`);
}
