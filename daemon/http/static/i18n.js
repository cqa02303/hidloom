"use strict";

const HIDLOOM_I18N_STORAGE_KEY = "hidloom-ui-language";
const HIDLOOM_I18N_SUPPORTED = new Set(["ja", "en"]);
const HIDLOOM_I18N_FALLBACK = "en";

const HIDLOOM_MESSAGES = {
  ja: {
    "language.label": "言語",
    "language.selectLabel": "表示言語",
    "language.auto": "自動",
    "actions.reload": "再読み込み",
    "system.title": "システム",
    "system.simple": "簡易",
    "system.detail": "詳細",
    "system.viewLabel": "ステータス表示",
    "tabs.label": "表示切り替え",
    "tabs.keyboard": "キーボード",
    "tabs.keymap": "キーコード変更",
    "tabs.lighting": "LEDエフェクト",
    "tabs.scripts": "スクリプト",
    "tabs.settings": "設定",
    "states.loading": "読み込み中…",
    "scripts.enterText": "文字列を入力してください",
    "scripts.selectScript": "スクリプトを選択してください",
  },
  en: {
    "language.label": "Language",
    "language.selectLabel": "Display language",
    "language.auto": "Automatic",
    "actions.reload": "Reload",
    "system.title": "System",
    "system.simple": "Simple",
    "system.detail": "Details",
    "system.viewLabel": "Status view",
    "tabs.label": "Switch view",
    "tabs.keyboard": "Keyboard",
    "tabs.keymap": "Keymap",
    "tabs.lighting": "LED Effects",
    "tabs.scripts": "Scripts",
    "tabs.settings": "Settings",
    "states.loading": "Loading…",
    "scripts.enterText": "Enter text",
    "scripts.selectScript": "Select a script",
  },
};

// Migration bridge for the existing UI. New UI uses semantic data-i18n keys;
// this table keeps legacy static and dynamically-created labels translatable
// while feature modules are migrated without changing their API behavior.
const HIDLOOM_JA_TO_EN = {
  "言語": "Language", "自動": "Automatic", "日本語": "Japanese",
  "簡易": "Simple", "詳細": "Details", "ログ": "Log", "更新": "Refresh",
  "キーボード": "Keyboard", "キーコード変更": "Keymap", "スクリプト": "Scripts",
  "レイヤー:": "Layer:", "Layer追加": "Add layer", "Layer削除": "Delete layer",
  ".vil書き出し": "Export .vil", ".vil読み込み": "Import .vil", "KLEで表示": "Open in KLE",
  "Matrix座標: OFF": "Matrix coordinates: OFF", "Matrix座標: ON": "Matrix coordinates: ON",
  "保存済みキー配置を初期化": "Reset saved keymap", "反映": "Apply", "リセット": "Reset",
  "再読込": "Reload", "保存・反映": "Save and apply", "既定値へ戻す": "Restore defaults",
  "幅": "Width", "高さ": "Height", "リサイズ": "Resize", "左クリック": "Left click",
  ": 点灯 /": ": on /", "右クリック": "Right click", ": 消去": ": erase",
  "塗りつぶし: OFF": "Fill: OFF", "塗りつぶし: ON": "Fill: ON", "全消去": "Clear all",
  "反転": "Invert", "このiconを戻す": "Restore this icon", "通常": "Normal",
  "反転badge": "Inverted badge", "Ready画面": "Ready screen",
  "表示、区切り線、上下順を変更できます。": "Change visibility, separators, and order.",
  "保存": "Save", "通常実行": "Run", "保存して実行": "Save and run",
  "チェック実行": "Check run", "初期化": "Reset", "組み込みコマンド": "Built-in commands",
  "挿入": "Insert", "HIDキーコード": "HID keycode", "hidloom-key tapを付ける": "Include hidloom-key tap",
  "キー挿入": "Insert key", "文字列挿入": "Insert text", "整形": "Format", "検証": "Validate",
  "保存してreload": "Save and reload", "保存のみ": "Save only", "入力欄へ": "Use in field",
  "例:": "Examples:", "設定": "Settings", "Webアクセス認証": "Web access authentication",
  "ユーザー名": "Username", "現在のパスワード": "Current password",
  "新しいパスワード": "New password", "新しいパスワード（確認）": "Confirm new password",
  "パスワードを変更": "Change password", "定型文送信": "Saved text entries",
  "＋ 定型文を追加": "+ Add saved text", "詳細編集（JSON）": "Advanced editing (JSON)",
  "定型文を保存": "Save text entries", "保存後すぐに反映": "Apply immediately after saving",
  "アナログスティック調整": "Analog stick calibration", "中心の測定時間（秒）": "Center sample time (seconds)",
  "可動範囲の測定時間（秒）": "Range sample time (seconds)", "必要な最小電圧幅（V）": "Required minimum span (V)",
  "1. 中心を測定": "1. Measure center", "中心を保存": "Save center",
  "2. 可動範囲を測定": "2. Measure range", "可動範囲を保存": "Save range",
  "3. 保存値を検査": "3. Validate saved values", "表示レイヤー:": "Display layer:",
  "実機": "Device", "置換": "Override", "キー入力転送: OFF": "Key passthrough: OFF",
  "キー入力転送: ON": "Key passthrough: ON", "内部キーテスター: OFF": "Matrix tester: OFF",
  "内部キーテスター: ON": "Matrix tester: ON", "全体表示: OFF": "Fullscreen keyboard: OFF",
  "送信: OFF": "Send: OFF", "送信: ON": "Send: ON", "削除": "Delete", "未定義": "Undefined",
  "読み込み中…": "Loading…", "読み込み中": "Loading", "読込中": "Loading",
  "保存中…": "Saving…", "保存中": "Saving", "同期済み": "Synchronized", "整形しました": "Formatted",
  "挿入しました": "Inserted", "反映中": "Applying", "反映済み": "Applied",
  "保存済み": "Saved", "既定値へ戻しました": "Restored defaults", "全消去しました": "Cleared",
  "文字列を入力してください": "Enter text", "スクリプトを選択してください": "Select a script",
  "取得失敗": "Fetch failed", "読込失敗": "Load failed", "保存失敗": "Save failed",
  "反映失敗": "Apply failed", "検査失敗": "Validation failed", "測定失敗": "Measurement failed",
  "エラー": "Error", "ログなし": "No log", "再読み込み": "Reload", "閉じる": "Close",
  "キャンセル": "Cancel", "確認": "Confirm", "追加": "Add", "選択": "Select", "検索": "Search",
  "有効": "Enabled", "無効": "Disabled", "復帰済み": "Restored", "送信中": "Sending",
  "下位レイヤーを透過": "Pass through to lower layer", "下位レイヤーのキー設定を使用": "Use the lower-layer key",
  "read-only: 実LED preview / 保存は後続": "Read-only: live LED preview and saving are planned",
  "Script safety: 危険操作メタデータ/自動検出なし": "Script safety: no dangerous-action metadata or automatic detection",
  "keycode / label / alias を検索": "Search keycode / label / alias",
  "Script は label / safety も見て選択": "Scripts also match label and safety metadata",
  "OLEDにワーニングメッセージを表示する": "Show a warning message on OLED",
  "OLEDに通常通知メッセージを表示する": "Show a normal notification on OLED",
  "OLED表示とjournal記録をまとめて行う": "Display on OLED and write to the journal",
  "通常通知をOLEDとjournalへ送る": "Send a normal notification to OLED and the journal",
  "文字列をキーボード入力として送る": "Send text as keyboard input",
  "HIDキーコードとmodifierを直接tapする": "Tap a HID keycode and modifiers directly",
  "次の処理まで少し待つ": "Wait briefly before the next command",
  "systemd journalにログを残す": "Write a message to the systemd journal",
  "logicd control socketからlayer状態を取得する": "Read layer state from the logicd control socket",
  "出力先をBluetoothへ切り替える": "Switch output to Bluetooth",
  "Bluetoothペアリング状態を切り替える": "Toggle Bluetooth pairing",
  "LED effectを直接指定する": "Set an LED effect directly",
  "1-bit iconとReady画面の表示順を編集します。保存内容はruntime overrideとして保持されます。": "Edit 1-bit icons and the Ready-screen order. Saved changes are kept as runtime overrides.",
  "変更する対象を選び、各カードの主操作で保存します。実機の動作を変える項目には、操作前の確認と結果を表示します。": "Choose what to change and use each card's primary action to save. Changes that affect the device show confirmation and results.",
  "この管理画面へアクセスするときのパスワードを変更します。ユーザー名は変更できません。": "Change the password used to access this interface. The username cannot be changed.",
  "名前を付けた定型文を登録し、Interactionの": "Register named text entries and call them from Interaction with",
  "から呼び出します。": ".",
  "① 中心から手を離して測定、② 外周まで大きく回して範囲を測定、③ 保存値を検査、の順に進めます。測定だけでは実機設定を変更しません。": "Proceed in order: 1) release the stick and measure center, 2) move it around the full edge and measure range, 3) validate saved values. Measurement alone does not change device settings.",
};

const HIDLOOM_JA_FRAGMENTS = [
  ["表示領域を ${overflow}px 超えています。項目を減らすか順序を調整してください。", "The layout exceeds the display by ${overflow}px. Remove or reorder items."],
  ["使用中: ${Math.max(0, y - 3)} / ${available - 3}px", "Used: ${Math.max(0, y - 3)} / ${available - 3}px"],
  ["${keycode} のsavedスクリプトを通常実行します。Continue?", "Run the saved script for ${keycode} normally. Continue?"],
  ["${keycode} のcurrent editor contentを will be run temporarily with httpd permissions.\\n", "The current editor content for ${keycode} will run temporarily with httpd permissions.\\n"],
  ["Toggle（target layerをtoggle）", "Toggle (toggle the target layer)"],
  ["LT(${layer}) のSelect a tap key", "Select the tap key for LT(${layer})"],
  ["/ LT(${_pendingLayerTap.layer}) のselecting a tap key", "/ selecting the tap key for LT(${_pendingLayerTap.layer})"],
  ["Layer再Load failed: ${e.message}", "Layer reload failed: ${e.message}"],
  ["savedKey配置 reset", "Saved key layout reset"],
  ["savedに戻しています", "Restoring saved state"],
  ["saved状態へ戻しました", "Restored saved state"],
  ["Bluetooth host ${mac} のdisplay name", "Display name for Bluetooth host ${mac}"],
  ["Script 10 は危険操作candidatesとして表示します", "Script 10 is shown as a potentially dangerous action"],
  ["dangerous scriptのCheck run canceled", "Dangerous-script check run canceled"],
  ["読込 complete", "Load complete"], ["読込 failed", "Load failed"], ["保存 failed", "Save failed"],
  ["リセット failed", "Reset failed"], ["取得 failed", "Fetch failed"], ["検査 failed", "Validation failed"],
  ["測定 failed", "Measurement failed"], ["Layer再読込 failed", "Layer reload failed"],
  ["反映 failed", "Apply failed"], ["OLED iconとReadyscreenをdefaultsへ戻?", "Restore OLED icons and the Ready screen to defaults?"],
  ["named entry は未settingsです", "No named entries are configured"],
  ["send_strings は JSON object にしてください", "send_strings must be a JSON object"],
  ["最小span電圧をcheckしてください", "Check the minimum span voltage"],
  ["保存値をcheckしてください", "Check the saved values"], ["測定秒数をcheckしてください", "Check the measurement duration"],
  ["range測定 canceled", "Range measurement canceled"], ["range測定中…", "Measuring range…"],
  ["rangeをSaved", "Saved range"], ["rangeを測定しました", "Measured range"],
  ["check用パスワードが一致しません", "The confirmation password does not match"],
  ["Saved。次のアクセスから新しいパスワードでlogインしてください。", "Saved. Use the new password on your next visit."],
  ["保存済み", "saved"], ["dangerous scriptの", "dangerous script "], [" canceled", " canceled"],
  ["通常実行 canceled", "Run canceled"], ["保存して実行 canceled", "Save and run canceled"],
  ["保存後にRunning", "Running after save"], ["現在のエディタcontent", "current editor content"],
  ["をRestore the initial template?", ": restore the initial template?"],
  [".vilをExportました", ".vil exported"], ["通信Error", "Communication error"],
  ["この.vilは別のUIDのKeyボード用です。現在の実機へLoadますか？", "This .vil is for a different keyboard UID. Load it on this device?"],
  [".vilをLoadました", ".vil loaded"], ["押している間だけ", "while held"],
  ["トグル切り替え", "toggle"], ["へ移動", "move to"], ["を変更", "change"],
  ["次の1Keyだけ", "for the next key only"], ["内部Keyコード（未分類・別名）", "Internal keycodes (uncategorized and aliases)"],
  ["短押しで次に選ぶKey、", "tap for the next selected key; "],
  ["InteractionsettingsをLoad中", "Loading Interaction settings"],
  ["下位Layerを透過", "Pass through to the lower layer"], ["下位LayerのKeysettingsを使用", "Use the lower-layer key setting"],
  ["タップKeyをSelect", "Select a tap key"], ["タップKeyを選択中", "selecting a tap key"],
  ["LTのタップKeyには通常KeyをSelect", "Select a regular key for the LT tap key"],
  ["Vial / HTTP UI から保存したKey配置をEraseし、config/default/keymap.json の初期配置へ戻します。Continue?", "Erase the keymap saved by Vial or the HTTP UI and restore config/default/keymap.json?"],
  ["保存済みKey配置 reset", "Saved keymap reset"], ["Bluetooth host", "Bluetooth host"],
  ["Bluetoothのペア済みデバイスdeleteします。Continue?", "Delete paired Bluetooth devices. Continue?"],
  ["(logなし)", "(no log)"], ["KLEでLayer", "Opened Layer"],
  ["Combo を builder にloaded into the builder", "Combo loaded into the builder"],
  ["Combo ${_interactionEditingComboIndex + 1} を builder にloaded into the builder", "Combo ${_interactionEditingComboIndex + 1} loaded into the builder"],
  ["Tap Dance を builder にloaded into the builder", "Tap Dance loaded into the builder"],
  ["Tap Dance ${_interactionEditingTapDanceIndex + 1} を builder にloaded into the builder", "Tap Dance ${_interactionEditingTapDanceIndex + 1} loaded into the builder"],
  ["Key Override を builder にloaded into the builder", "Key Override loaded into the builder"],
  ["Key Override ${_interactionEditingOverrideIndex + 1} を builder にloaded into the builder", "Key Override ${_interactionEditingOverrideIndex + 1} loaded into the builder"],
  ["Layer Lock をRemoveしました", "Layer Lock cleared"], ["Layer Lock は既にRemove済みです", "Layer Lock is already clear"],
  ["Advanced Timing をapplied", "Advanced Timing applied"], ["Conditional source layer がcontains duplicates", "Conditional source layers contain duplicates"],
  ["は 0-31 のmust be an integer", "must be an integer from 0 to 31"],
  ["conditional_layers はmust be an array", "conditional_layers must be an array"],
  ["Conditional Layer rule Add しました", "Conditional Layer rule added"], ["Conditional Layer rule deleteしました", "Conditional Layer rule deleted"],
  ["Text Send plan の action is empty", "Text Send plan action is empty"], ["は at least 0 must be an integer", "must be an integer of at least 0"],
  ["Combo key がcontains duplicates", "Combo keys contain duplicates"],
  ["Keyボード上の source key をSelect", "select a source key on the keyboard"],
  ["Combo action をEnter a value", "Enter a Combo action"], ["combos はmust be an array", "combos must be an array"],
  ["Combo をupdated", "Combo updated"], ["Combo Add しました", "Combo added"],
  ["Tap Dance ${name} はalready exists", "Tap Dance ${name} already exists"], ["Tap Dance をupdated", "Tap Dance updated"],
  ["Tap Dance Add しました", "Tap Dance added"], ["Override の入力is incomplete", "Override input is incomplete"],
  ["key_overrides はmust be an array", "key_overrides must be an array"], ["Key Override をupdated", "Key Override updated"],
  ["Key Override Add しました", "Key Override added"], ["Morse editor のcontentをcheckしてください", "Check the Morse editor content"],
  ["Morse ${name} をLoadました", "Morse ${name} loaded"], ["Morse ${name} Add しました", "Morse ${name} added"],
  ["Morse 追加 canceled", "Morse add canceled"], ["Morse ${name} をadded or updated", "Morse ${name} added or updated"],
  ["Morse ${name} deleteしました", "Morse ${name} deleted"], ["Layer ${nextLayer} Add しました", "Layer ${nextLayer} added"],
  ["Layer追加Error", "Layer add error"], ["Layer 0 は削除できません", "Layer 0 cannot be deleted"],
  ["Layer ${layer} delete相当として全Key KC_TRNS に戻します。\\n", "Reset all keys on Layer ${layer} to KC_TRNS (equivalent to deletion).\\n"],
  ["Layer ${layer} deleteしました", "Layer ${layer} deleted"], ["Layer ${layer} を KC_TRNS に初期化しました", "Layer ${layer} reset to KC_TRNS"],
  ["Layer削除Error", "Layer delete error"],
  ["Wi-Fi Off は SSH / HTTP UI 接続を切る可能性があります。\\n再起動すると既定で Wi-Fi は復帰します。割り当てますか？", "Wi-Fi Off may disconnect SSH and the HTTP UI.\\nWi-Fi returns to its default on state after reboot. Assign it?"],
  ["危険操作候補を検出しました", "A potentially dangerous action was detected"],
  ["本当にチェック実行しますか？", "Run the check anyway?"], ["本当に実行しますか？", "Run it anyway?"],
  ["実行前に追加確認します。", "Additional confirmation is required before running."],
  ["チェック実行をキャンセルしました", "Check run canceled"],
  ["未実装・未対応候補は", "For unimplemented or unsupported candidates, see"],
  ["を確認。追加時は", ". When adding one, keep"], ["を同期します。", "in sync."],
  ["OLED iconとReadyscreenを既定値へ戻しますか？", "Restore OLED icons and the Ready screen to defaults?"],
  ["測定中にスティックを外周まで大きく回してください。最大/最小を保存します。", "Move the stick around its full outer range during measurement. The minimum and maximum will be saved."],
  ["保存はされませんが、スクリプト内のコマンドは実行されます。続行しますか？", "It will not be saved, but commands in the script will run. Continue?"],
  ["Vial / HTTP UI から保存したKey配置をEraseし、config/default/keymap.json の初期配置へ戻します。よろしいですか？", "Erase the keymap saved from Vial or the HTTP UI and restore config/default/keymap.json?"],
  ["この.vilは別のUIDのKeyボード用です。現在の実機へLoadますか？", "This .vil belongs to a different keyboard UID. Load it on this device?"],
  ["MORSE(name) の分岐を read-only 表示します。leaf は自動確定、force_commit は枝があっても強制確定です。fallback_action は不発時に発行されます。", "Shows MORSE(name) branches read-only. Leaves commit automatically; force_commit commits even with branches; fallback_action runs when no match occurs."],
  ["Momentary（押している間だけ対象Layer）", "Momentary (active while held)"],
  ["Toggle（対象Layerをトグル切り替え）", "Toggle (toggle target layer)"],
  ["To（対象Layerへ移動）", "To (move to target layer)"],
  ["Default（既定Layerを変更）", "Default (change default layer)"],
  ["One Shot（次の1Keyだけ対象Layer）", "One Shot (target layer for the next key)"],
  ["Layer Tap（短押しで次に選ぶKey、押している間だけ対象Layer）", "Layer Tap (tap the next selected key; hold for target layer)"],
  ["Wi-Fi Control（既定は再起動で on に戻る一時操作）", "Wi-Fi Control (temporary; returns on after reboot by default)"],
  ["Interactionタブで Tap Dance / Morse を定義するとここに表示されます", "Definitions created in the Interaction tab appear here"],
  ["Layer ${layer} を削除相当として全Key KC_TRNS に戻します。\\n", "Reset every key on Layer ${layer} to KC_TRNS (equivalent to deleting it).\\n"],
  ["layer 番号は詰めません。よろしいですか？", "Layer numbers will not be renumbered. Continue?"],
  ["Combo Key ${index}: Keyボード上の source key を選択してください", "Combo key ${index}: select a source key on the keyboard"],
  ["Morse name は A-Z a-z 0-9 _ . - の1〜64文字にしてください", "Morse name must be 1–64 characters using A-Z, a-z, 0-9, _, ., or -"],
  ["新しい Morse 定義名", "New Morse definition name"],
  ["Defined から更新する Morse 定義を選択してください", "Select a Morse definition to update from Defined"],
  ["Defined からコピーする Morse 定義を選択してください", "Select a Morse definition to copy from Defined"],
  ["Conditional source layer は 2 個以上", "Enter at least two Conditional source layers"],
  ["Conditional source layer は 0-31 の", "Conditional source layers must be 0–31 "],
  ["Conditional target layer は source layer と分けてください", "Conditional target layer must differ from source layers"],
  ["Combo は 2 個以上の key が必要です", "A Combo needs at least two keys"],
  ["Tap Dance action を 1 つ以上", "Enter at least one Tap Dance action"],
  ["Morse map を 1 行以上", "Enter at least one Morse map row"],
  ["KLEレイアウト情報がありません", "KLE layout information is unavailable"],
  ["ポップアップがブロックされました", "The popup was blocked"],
  ["表示できるスクリプトがありません", "No scripts are available to display"],
  ["LED番号をクリックして追加", "Click an LED number to add it"], ["LED座標がありません", "No LED coordinates are available"],
  ["restore state がありません", "No restore state is available"], ["effect復帰済み", "Effect restored"],
  ["keycode/text actionを送信できるようにします", "Enable sending keycode/text actions"],
  ["keycode/text actionを送信します", "Send keycode/text actions"],
  ["httpd 権限で一時実行します。", "will be run temporarily with httpd permissions."],
  ["初期テンプレートに戻します。よろしいですか？", "Restore the initial template?"],
  ["の保存済みスクリプトを通常実行します。続行しますか？", "Run the saved script normally. Continue?"],
  ["を保存してから通常実行します。続行しますか？", "Save and then run normally. Continue?"],
  ["取得 failed", "Fetch failed"], ["読込 failed", "Load failed"], ["保存 failed", "Save failed"],
  ["測定 failed", "Measurement failed"], ["リセット failed", "Reset failed"],
  ["読込 complete", "Loaded"], ["読込中…", "Loading…"], ["読込中...", "Loading..."],
  ["リセット中…", "Resetting…"], ["リセット中", "Resetting"],
  ["preview送信中", "Sending preview"], ["preview中", "Previewing"], ["restore送信中", "Sending restore"],
  ["通常実行 canceled", "Run canceled"], ["通常実行中", "Running"],
  ["保存して実行 canceled", "Save and run canceled"], ["保存後に通常実行中", "Running after save"],
  ["チェック実行 canceled", "Check run canceled"], ["チェック実行中", "Check running"],
  ["保存+reload中…", "Saving and reloading…"], ["保存+reload完了", "Save and reload complete"],
  ["保存完了", "Save complete"], ["検証中…", "Validating…"], ["検証完了", "Validation complete"],
  ["warnings なし", "No warnings"], ["Morse tree warnings なし", "No Morse tree warnings"],
  ["待機中", "Waiting"], ["開く", "Open"], ["子 node を開閉", "Toggle child node"],
  ["コピーできませんでした", "Copy failed"], ["コピー用 action", "Action to copy"],
  ["未作成", "Not created"], ["初期状態", "Initial state"], ["スクリプトなし", "No scripts"],
  ["未分類のicon", "Uncategorized icons"], ["即時反映", "Apply immediately"],
  ["定期更新で反映", "Apply on periodic refresh"], ["表示する", "Show"], ["線", "Line"],
  ["Pin解除", "Unpin"], ["Pinに追加", "Pin"], ["メディア", "Media"],
  ["ショートカット", "Shortcuts"], ["特殊", "Special"], ["日本語IME", "Japanese IME"],
  ["内部Keyコード（未分類・別名）", "Internal keycodes (uncategorized and aliases)"],
  ["QMK code を", "QMK code: "], ["Action選択", "Select action"],
  ["現在:", "Current:"], ["変更モード: ON", "Edit mode: ON"],
  ["system default 初期配置 デフォルト", "System default initial layout"],
  ["Interaction設定をLoad中", "Loading Interaction settings"],
  ["Layer再読込", "Layer reload"], ["スクリプト情報読込", "Script information load"],
  ["Interaction情報読込", "Interaction information load"], ["不明なエラー", "Unknown error"],
  ["初期化エラー", "Reset error"], ["保存済みKey配置", "Saved keymap"],
  ["エラー", "Error"], ["通信エラー", "Communication error"], ["警告", "warnings"],
  ["件", " items"], ["Keyボード", "keyboard"], ["タップKey", "tap key"],
  ["通常Key", "regular key"], ["下位Layer", "lower layer"], ["Key設定", "key setting"],
  ["対象Layer", "target layer"], ["既定Layer", "default layer"], ["日本語", "Japanese"],
  ["番号をクリックして", "Click a number to"], ["座標がありません", "coordinates are unavailable"],
  ["が空です", "is empty"], ["が不足しています", "is incomplete"], ["が必要です", "is required"],
  ["は object にしてください", "must be an object"], ["は未定義です", "is undefined"],
  ["未定義", "Undefined"], ["既に存在します", "already exists"], ["内容", "content"],
  ["追加/更新しました", "added or updated"], ["更新しました", "updated"],
  ["入力が不足しています", "input is incomplete"], ["action が", "action "],
  ["を preview しました", "previewed"], ["の row/col", "row/col for "],
  ["0 以上の", "at least 0 "], ["個以上", "or more"], ["個", ""],
  ["を追加", "Add "], ["から更新する", "to update from"], ["からコピーする", "to copy from"],
  ["追加 canceled", "add canceled"], ["追加/更新", "add/update"], ["コピーする", "copy"],
  ["分岐", "branches"], ["不発時", "when unmatched"], ["発行されます", "is emitted"],
  ["開閉", "toggle"], ["をLoadました", " loaded"], ["をLoad", "load "],
  ["をExportました", " exported"], ["Exportエラー", "export error"], ["Loadエラー", "load error"],
  ["再起動", "reboot"], ["戻る", "return"], ["一時操作", "temporary action"],
  ["接続を切る可能性があります", "may disconnect"], ["割り当てますか？", "Assign it?"],
  ["の割り当て", "assignment of "], ["前に追加確認します", "requires additional confirmation first"],
  ["を検出しました", "detected"], ["本当に", "Really "], ["しますか？", "?"],
  ["解除", "Remove"], ["追加時", "When adding"], ["確認", "check"], ["同期", "sync"],
  ["未実装", "Unimplemented"], ["未対応", "unsupported"], ["候補", "candidates"],
  ["塗りつぶし", "Fill"], ["既定値", "defaults"], ["戻しますか？", "Restore?"],
  ["最大/最小", "range"], ["外周", "outer range"], ["大きく回してください", "move fully around"],
  ["スティック", "stick"], ["コマンド", "commands"], ["実行されます", "will run"],
  ["続行", "Continue"], ["対象操作", "Target action"], ["よろしいですか？", "Continue?"],
  ["情報がありません", "information is unavailable"], ["ブロックされました", "was blocked"],
  ["を開きました", "opened"], ["表示できる", "displayable"], ["ありません", "none"],
  ["設定", "settings"], ["タブ", "tab"], ["ここに表示されます", "appear here"],
  ["反映済み / 保存待ち", "Applied / waiting to save"], ["保存待ち", "waiting to save"],
  ["ホスト", "host"], ["表示名", "display name"], ["ログ", "log"],
  ["読み戻しました", "loaded into the builder"], ["反映しました", "applied"],
  ["以上", "or higher"], ["選択してください", "Select"], ["空です", "is empty"],
  ["を更新", "update"], ["を削除", "delete"], ["を追加", "add"],
  ["警告なし", "No warnings"], ["定義名", "definition name"], ["1〜64文字", "1–64 characters"],
  ["全Key", "all keys"], ["削除相当", "equivalent to deletion"], ["番号は詰めません", "numbers will not be renumbered"],
  ["保存済み状態へ戻しました", "Restored the saved state"], ["保存済みに戻しています", "Restoring the saved state"],
  ["保存・反映依頼済み", "Save and apply requested"], ["最大/最小測定をキャンセルしました", "Range measurement canceled"],
  ["最大/最小測定中…", "Measuring range…"], ["中心測定中…", "Measuring center…"],
  ["中心を測定しました", "Measured center"], ["最大/最小を測定しました", "Measured range"],
  ["中心を保存しました", "Saved center"], ["最大/最小を保存しました", "Saved range"],
  ["保存値を検査中…", "Validating saved values…"], ["保存値は有効です", "Saved values are valid"],
  ["保存値を確認してください", "Check the saved values"], ["測定秒数を確認してください", "Check the measurement duration"],
  ["最小span電圧を確認してください", "Check the minimum span voltage"],
  ["確認用パスワードが一致しません", "The confirmation password does not match"],
  ["新しいパスワードを入力してください", "Enter a new password"],
  ["次のアクセスから新しいパスワードでログインしてください。", "Use the new password on your next visit."],
  ["をコピーしました", " copied"], ["をPlan actionへ入れました", " added to Plan action"],
  ["name を入力してください", "Enter a name"], ["named entry は未設定です", "No named entries are configured"],
  ["Plan action を入力してください", "Enter a Plan action"], ["Plan preview中…", "Loading Plan preview…"],
  ["Bluetoothのペア済みデバイスを削除します。続行しますか？", "Delete paired Bluetooth devices. Continue?"],
  ["表示名", "display name"], ["Layer Lock を解除しました", "Layer Lock cleared"],
  ["Layer Lock は既に解除済みです", "Layer Lock is already clear"],
  ["JSON root は object にしてください", "The JSON root must be an object"],
  ["配列にしてください", "must be an array"], ["整数にしてください", "must be an integer"],
  ["入力してください", "Enter a value"], ["重複しています", "contains duplicates"],
  ["を追加しました", " added"], ["を削除しました", " deleted"], ["を選択しました", " selected"],
  ["を入力欄へ入れました", " added to the input field"], ["を読み戻しました", " loaded back into the builder"],
  ["をキャンセルしました", " canceled"], ["を初期化しました", " reset"],
  ["レイアウト取得", "Layout fetch"], ["を確認してください", "Check "], ["失敗:", " failed:"], ["完了:", " complete:"],
  ["読込完了:", "Loaded:"], ["保存しました", "Saved"], ["取得しました", "Fetched"],
  ["全体表示を閉じる", "Exit fullscreen"], ["キーボードだけを全体表示", "Show keyboard fullscreen"],
  ["キーコード変更画面のキー中央に matrix row,col を表示", "Show matrix row,col in the center of keys in the keymap view"],
  ["レイアウト取得失敗", "Layout fetch failed"], ["実機:", "Device:"], ["表示:", "Display:"],
  ["で置換", " override"], ["から表示", " shown from"], ["は KC_TRNS", "is KC_TRNS"],
  ["危険操作候補", "potentially dangerous action"], ["危険script", "dangerous script"],
  ["割り当てをキャンセルしました", "assignment canceled"], ["未解析", "not analyzed"],
  ["読み込み", "Load"], ["書き出し", "Export"], ["点灯", "On"], ["消去", "Erase"],
  ["レイヤー", "Layer"], ["キー", "Key"], ["文字列", "Text"], ["画面", "screen"],
];

const _hidloomOriginalText = new WeakMap();
const _hidloomOriginalAttributes = new WeakMap();
let _hidloomApplyingLegacyTranslations = false;

function normalizeHidloomLanguage(value) {
  const primary = String(value || "").trim().toLowerCase().split(/[-_]/, 1)[0];
  return HIDLOOM_I18N_SUPPORTED.has(primary) ? primary : "";
}

function hidloomRequestedLanguage() {
  const query = new URLSearchParams(window.location.search).get("lang");
  if (query) return query === "auto" ? "auto" : normalizeHidloomLanguage(query);
  try {
    const stored = window.localStorage.getItem(HIDLOOM_I18N_STORAGE_KEY);
    if (stored) return stored === "auto" ? "auto" : normalizeHidloomLanguage(stored);
  } catch (_error) {
    // A blocked localStorage must not prevent the UI from loading.
  }
  return "auto";
}

function hidloomBrowserLanguage() {
  const candidates = Array.isArray(navigator.languages) && navigator.languages.length
    ? navigator.languages
    : [navigator.language];
  for (const candidate of candidates) {
    const normalized = normalizeHidloomLanguage(candidate);
    if (normalized) return normalized;
  }
  return HIDLOOM_I18N_FALLBACK;
}

let _hidloomLanguagePreference = hidloomRequestedLanguage() || "auto";
let _hidloomLanguage = _hidloomLanguagePreference === "auto"
  ? hidloomBrowserLanguage()
  : _hidloomLanguagePreference;

function hidloomTranslate(key, variables = {}) {
  const messages = HIDLOOM_MESSAGES[_hidloomLanguage] || HIDLOOM_MESSAGES[HIDLOOM_I18N_FALLBACK];
  const fallback = HIDLOOM_MESSAGES[HIDLOOM_I18N_FALLBACK];
  let text = messages[key] ?? fallback[key] ?? key;
  for (const [name, value] of Object.entries(variables)) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

function hidloomTranslateJapaneseText(value) {
  const source = String(value ?? "");
  if (_hidloomLanguage !== "en" || !/[ぁ-んァ-ヶ一-龠]/.test(source)) return source;
  const leading = source.match(/^\s*/)?.[0] || "";
  const trailing = source.match(/\s*$/)?.[0] || "";
  const content = source.slice(leading.length, source.length - trailing.length || undefined);
  if (HIDLOOM_JA_TO_EN[content]) return `${leading}${HIDLOOM_JA_TO_EN[content]}${trailing}`;
  let translated = content;
  // A replacement can expose a shorter phrase that appears earlier in the
  // table. Repeat to a fixed point so legacy compound messages are translated
  // completely instead of leaving a Japanese/English mixture.
  for (let pass = 0; pass < 5; pass += 1) {
    const before = translated;
    for (const [japanese, english] of HIDLOOM_JA_FRAGMENTS) {
      translated = translated.replaceAll(japanese, english);
    }
    if (translated === before) break;
  }
  return `${leading}${translated}${trailing}`;
}

function hidloomTranslationExcluded(element) {
  if (!element) return true;
  if (element.closest("[data-i18n], [data-i18n-title], [data-i18n-aria-label]")) return false;
  return Boolean(element.closest(
    "script, style, code, pre, textarea, #keyboard, [data-i18n-skip]"
  ));
}

function applyHidloomLegacyText(root = document.body) {
  if (!root || typeof document.createTreeWalker !== "function") return;
  _hidloomApplyingLegacyTranslations = true;
  try {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (hidloomTranslationExcluded(node.parentElement)) continue;
      if (!_hidloomOriginalText.has(node)) _hidloomOriginalText.set(node, node.nodeValue || "");
      const original = _hidloomOriginalText.get(node);
      node.nodeValue = _hidloomLanguage === "ja" ? original : hidloomTranslateJapaneseText(original);
    }

    const attributeRoot = root.nodeType === Node.ELEMENT_NODE ? root : document;
    attributeRoot.querySelectorAll?.("[title], [placeholder], [aria-label]").forEach(element => {
      if (hidloomTranslationExcluded(element)) return;
      let originals = _hidloomOriginalAttributes.get(element);
      if (!originals) {
        originals = {};
        _hidloomOriginalAttributes.set(element, originals);
      }
      for (const attribute of ["title", "placeholder", "aria-label"]) {
        if (!element.hasAttribute(attribute)) continue;
        if (!(attribute in originals)) originals[attribute] = element.getAttribute(attribute) || "";
        element.setAttribute(attribute, _hidloomLanguage === "ja"
          ? originals[attribute]
          : hidloomTranslateJapaneseText(originals[attribute]));
      }
    });
  } finally {
    _hidloomApplyingLegacyTranslations = false;
  }
}

function applyHidloomTranslations(root = document) {
  root.querySelectorAll("[data-i18n]").forEach(element => {
    element.textContent = hidloomTranslate(element.dataset.i18n);
  });
  root.querySelectorAll("[data-i18n-title]").forEach(element => {
    element.title = hidloomTranslate(element.dataset.i18nTitle);
  });
  root.querySelectorAll("[data-i18n-aria-label]").forEach(element => {
    element.setAttribute("aria-label", hidloomTranslate(element.dataset.i18nAriaLabel));
  });
  document.documentElement.lang = _hidloomLanguage;
  applyHidloomLegacyText(root === document ? document.body : root);
}

function setHidloomLanguage(preference, options = {}) {
  const normalized = preference === "auto" ? "auto" : normalizeHidloomLanguage(preference);
  if (!normalized) return false;
  _hidloomLanguagePreference = normalized;
  _hidloomLanguage = normalized === "auto" ? hidloomBrowserLanguage() : normalized;
  if (options.persist !== false) {
    try {
      window.localStorage.setItem(HIDLOOM_I18N_STORAGE_KEY, normalized);
    } catch (_error) {
      // Keep the in-memory selection when persistence is unavailable.
    }
  }
  applyHidloomTranslations();
  const selector = document.getElementById("ui-language");
  if (selector) selector.value = normalized;
  window.dispatchEvent(new CustomEvent("hidloomlanguagechange", {
    detail: { language: _hidloomLanguage, preference: normalized },
  }));
  return true;
}

function initHidloomI18n() {
  applyHidloomTranslations();
  const selector = document.getElementById("ui-language");
  if (!selector) return;
  selector.value = _hidloomLanguagePreference;
  selector.addEventListener("change", () => setHidloomLanguage(selector.value));

  const observer = new MutationObserver(mutations => {
    if (_hidloomApplyingLegacyTranslations) return;
    for (const mutation of mutations) {
      if (mutation.type === "childList") {
        mutation.addedNodes.forEach(node => {
          if (node.nodeType === Node.TEXT_NODE) applyHidloomLegacyText(node.parentElement);
          else if (node.nodeType === Node.ELEMENT_NODE) applyHidloomLegacyText(node);
        });
      } else if (mutation.type === "attributes") {
        const element = mutation.target;
        const attribute = mutation.attributeName;
        const current = element.getAttribute(attribute) || "";
        if (_hidloomLanguage === "en" && /[ぁ-んァ-ヶ一-龠]/.test(current)) {
          let originals = _hidloomOriginalAttributes.get(element);
          if (!originals) {
            originals = {};
            _hidloomOriginalAttributes.set(element, originals);
          }
          originals[attribute] = current;
          element.setAttribute(attribute, hidloomTranslateJapaneseText(current));
        }
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["title", "placeholder", "aria-label"],
  });
}

window.hidloomI18n = {
  apply: applyHidloomTranslations,
  get language() { return _hidloomLanguage; },
  get preference() { return _hidloomLanguagePreference; },
  normalize: normalizeHidloomLanguage,
  setLanguage: setHidloomLanguage,
  t: hidloomTranslate,
  translateJapanese: hidloomTranslateJapaneseText,
};

const _hidloomNativeConfirm = window.confirm.bind(window);
const _hidloomNativePrompt = window.prompt.bind(window);
const _hidloomNativeAlert = window.alert.bind(window);
window.confirm = message => _hidloomNativeConfirm(hidloomTranslateJapaneseText(message));
window.prompt = (message, defaultValue) => _hidloomNativePrompt(hidloomTranslateJapaneseText(message), defaultValue);
window.alert = message => _hidloomNativeAlert(hidloomTranslateJapaneseText(message));

document.addEventListener("DOMContentLoaded", initHidloomI18n);
