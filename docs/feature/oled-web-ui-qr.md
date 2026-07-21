# OLED Web UI QR

更新日: 2026-07-20

## 目的

OLEDのReady画面へ、HIDloom HTTP管理画面のaddressを読み取るためのQRコードを表示します。
HTTP OLED EditorのReady画面要素`Web UI QR`として、表示ON/OFF、上下順、区切り線を変更できます。
既定はOFFです。

## 表示仕様

- QR Code Model 2、Version 1、error correction level L
- 英数字mode、最大25文字
- 21×21 modules、1 moduleあたり2×2 pixels
- 四辺に4 modulesずつquiet zoneを確保
- quiet zone込み58×58pxを64×128px OLEDの中央へ配置
- 現在のroutable IPv4から`HTTPS://<IPv4 address>`を生成
- password、Basic認証header、cookie、CSRF tokenは格納しない
- address未解決、容量超過、非対応文字の場合はQRを生成せず`Web UI / No address`を表示

HTTP OLED Editorのpreviewも同じ58×58pxを使います。Ready要素の合計が128pxを超える場合は、
保存前に表示要素を減らすか順序を変えられるよう超過pixel数を警告します。

## 互換性

以前の`/mnt/p3/oled_customization.json`には`web_ui_qr`がありません。
読込時に既定OFF・区切り線OFFで末尾へ追加し、既存要素の有効状態と順序は保持します。
保存schemaは`hidloom.oled.customization.v1`のままです。

## 実装と検証

`daemon/i2cd/qr_v1.py`はOLED用途に限定した、外部runtime依存のないVersion 1-L英数字encoderです。
既知vector、容量、文字種、quiet zone、pixel scalingを回帰testで固定しています。
文書用予約アドレス`HTTPS://192.0.2.1`の生成画像は独立したOpenCV QRCodeDetectorで同じ文字列へdecodeできることを確認しています。

実機では一時的にQRだけをReady画面へ表示してi2cdの描画経路を確認し、その後元のruntime customizationへ復元します。
通常運用で表示する場合はHTTP OLED Editorから`Web UI QR`をONにして保存します。

`KC_SH3`を押した場合は、従来どおりNode / SSID / IPを4秒表示した後、管理画面QRを15秒間だけ表示し、
スクリプト終了表示を経てReady画面へ戻ります。この一時表示はOLED Editorの`Web UI QR`設定とは独立しており、
固定表示をOFFにしていても利用できます。固定表示のON/OFF、並び順、区切り線の機能は従来どおり維持されます。

## 権利と商標

デンソーウェーブ公式FAQによると、JIS / ISO規格に従うQRコードの作成・読取には申請、
ライセンス契約、使用料は必要ありません。登録商標はQRコードの図柄ではなく「QRコード」という語に適用され、
出版物やWeb siteなどでこの語を使う場合は商標注記を表示するよう案内されています。

「QRコード」は株式会社デンソーウェーブの登録商標です。

- [株式会社デンソーウェーブ QRコードFAQ](https://www.qrcode.com/faq.html/header.html)
- [QRコードの規格化・標準化](https://www.qrcode.com/about/standards.html)
- [QRコード領域とquiet zone](https://www.qrcode.com/howto/code.html)

HIDloomは株式会社デンソーウェーブの製品ではなく、同社による後援、認定、保証を受けたものではありません。
