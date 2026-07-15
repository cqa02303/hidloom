"use strict";

// .vil import/export actions for the remap panel. The panel owns keyboard
// rendering; this module only handles file transfer and asks it to refresh.

async function exportVilLayout() {
  try {
    const resp = await fetch("/api/vil/export");
    if (!resp.ok) {
      showToast(`.vil書き出しエラー: HTTP ${resp.status}`, true);
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    link.href = url;
    link.download = match ? match[1] : "layout.vil";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    const warningCount = Number(resp.headers.get("X-HIDLOOM-VIL-Warnings") || "0");
    const warningText = warningCount > 0 ? ` / 警告 ${warningCount}件` : "";
    showToast(`.vilを書き出しました${warningText}`);
  } catch (e) {
    showToast(`通信エラー: ${e.message}`, true);
  }
}

async function importVilLayout(file, forceUid = false) {
  if (!file) return;
  try {
    const content = await file.text();
    const resp = await csrfFetch("/api/vil/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, force_uid: forceUid }),
    });
    const data = await resp.json();
    if (resp.status === 409 && data.result === "uid_mismatch") {
      const ok = window.confirm(
        "この.vilは別のUIDのキーボード用です。現在の実機へ読み込みますか？"
      );
      if (ok) {
        await importVilLayout(file, true);
      }
      return;
    }
    if (!resp.ok || data.result !== "ok") {
      showToast(`.vil読み込みエラー: ${data.msg || resp.status}`, true);
      return;
    }
    await refreshRemapAfterExternalKeymapUpdate();
    const warningText = data.warnings && data.warnings.length ? ` / 警告 ${data.warnings.length}件` : "";
    showToast(`.vilを読み込みました (${data.applied || 0}件${warningText})`);
  } catch (e) {
    showToast(`通信エラー: ${e.message}`, true);
  }
}
