# Windows driver usage

このフォルダは、CQA02303v5 を Windows で main keyboard = JIS 106/109、
sub keyboard = US 101/102 として認識させるための実験用 driver package を置く場所です。

対象ファイル:

- `cqa02303v5-jis-keyboard.inf`: main `MI_00&COL01` を JIS、sub `MI_02` を US として bind する INF。
- `build-sign-install-cqa-jis-inf-admin.ps1`: INF を package 化し、自己署名 catalog を作成して install する管理者用 script。
- `install-cqa-jis-inf-admin.ps1`: 署名済み package を使わず、INF を直接 `pnputil` に渡す最小 script。
- `cqa02303v5-keyboard-layout-override-template.reg`: 手動 registry override 実験用の控え。通常手順では使わない。

## 前提

- Windows の管理者 PowerShell で実行する。
- Windows SDK の `signtool.exe` が必要。
  現在の script は次の path を前提にしている。

```powershell
C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe
```

違う version の Windows SDK を使う場合は、`build-sign-install-cqa-jis-inf-admin.ps1` の
`$SignTool` を実機に合わせて変更する。

## 通常の install 手順

1. CQA02303v5 を Windows host に USB 接続する。
2. 管理者 PowerShell を開く。
3. このフォルダへ移動する。

```powershell
cd "<repo>\windows-driver"
```

4. build / sign / install script を実行する。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build-sign-install-cqa-jis-inf-admin.ps1
```

成功すると、`package\cqa02303v5-jis-keyboard.inf` と
`package\cqa02303v5-jis-keyboard.cat` が作られ、`pnputil /add-driver ... /install`
で install される。log は `build-sign-install-cqa-jis-inf.log` に残る。

## 確認

Device Manager の Keyboards で、次の 2 つの keyboard child がこの INF に bind されていることを確認する。

- `CQA02303v5 Japanese 106/109 USB Keyboard`
- `CQA02303v5 US 101/102 Sub Keyboard`

PowerShell では次のように確認できる。

```powershell
Get-PnpDevice -Class Keyboard | Where-Object FriendlyName -like "CQA02303v5*"
```

期待する入力解釈:

- main keyboard: JIS 106/109 として扱われる。
- sub keyboard: US 101/102 として扱われる。

`jis_special_us_default` route を使う運用では、通常キーと `KC_LANG1` / `KC_LANG2` は
US sub 側へ、`KC_KANA`、変換、無変換、RO、Yen などの JIS 固有キーは main JIS 側へ送る。

## 失敗時の確認

`build-sign-install-cqa-jis-inf-admin.ps1` が失敗した場合は、まず log を見る。

```powershell
Get-Content .\build-sign-install-cqa-jis-inf.log -Tail 80
```

よく見る箇所:

- `signtool.exe` の path が実機の Windows SDK と合っているか。
- 管理者 PowerShell で実行しているか。
- `pnputil` が署名または catalog を拒否していないか。
- Device Manager 上で stale な古い CQA02303v5 device instance が残っていないか。

古い device instance が疑わしい場合は、接続状態と Device Manager の表示を確認してから、
必要に応じて repository root の `script\cleanup_windows_cqa_stale_devices.ps1` を使う。

## 戻し方

Windows が作成した `oem*.inf` 名を確認する。

```powershell
pnputil /enum-drivers | Select-String -Context 0,8 "CQA02303v5"
```

確認した `Published Name` を使って削除する。

```powershell
pnputil /delete-driver oemNNN.inf /uninstall /force
```

削除後、CQA02303v5 を抜き差しして、Windows の標準 HID keyboard bind に戻ることを確認する。

## registry template について

`cqa02303v5-keyboard-layout-override-template.reg` は、INF 化前に使った手動 registry override の控え。
device instance path は USB serial、port、再列挙状態で変わるため、そのまま import しない。
通常運用では custom INF route を使う。
