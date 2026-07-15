$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageRoot = Join-Path $Root "package"
$InfSource = Join-Path $Root "cqa02303v5-jis-keyboard.inf"
$InfPath = Join-Path $PackageRoot "cqa02303v5-jis-keyboard.inf"
$CatPath = Join-Path $PackageRoot "cqa02303v5-jis-keyboard.cat"
$CerPath = Join-Path $Root "cqa02303v5-test-driver-signing.cer"
$LogPath = Join-Path $Root "build-sign-install-cqa-jis-inf.log"
$Subject = "CN=CQA02303v5 Test Driver Signing"
# -----------------------------------------------------------------
# Windows SDKのインストール先から自動的に signtool.exe を検索する
# -----------------------------------------------------------------
$SdkRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
$SignTool = $null

if (Test-Path $SdkRoot) {
    # 10.0.xxxxx.0 のようなバージョンフォルダ内にある x64 用の signtool.exe をすべて取得
    # バージョン番号（名前）で降順ソートして、最新のものを1つだけ選択
    $SignTool = Get-ChildItem -Path $SdkRoot -Filter "signtool.exe" -Recurse |
                Where-Object { $_.FullName -match '\\x64\\' } |
                Sort-Object -Property Directory -Descending |
                Select-Object -ExpandProperty FullName -First 1
}

# 見つからなかった場合の安全装置
if (-not $SignTool) {
    throw "signtool.exe が見つかりませんでした。Windows SDK がインストールされているか確認してください。"
}


function Log($Message) {
    $Message | Tee-Object -FilePath $LogPath -Append
}

Set-Content -Path $LogPath -Value "CQA02303v5 JIS INF build/sign/install log"
Log "Using SignTool: $SignTool"

Log "Root: $Root"

if (-not (Test-Path $PackageRoot)) {
    New-Item -ItemType Directory -Path $PackageRoot | Out-Null
}

Copy-Item -Path $InfSource -Destination $InfPath -Force
if (Test-Path $CatPath) {
    Remove-Item -Path $CatPath -Force
}

Log "Creating catalog: $CatPath"
New-FileCatalog -Path $PackageRoot -CatalogFilePath $CatPath -CatalogVersion 2.0 | Out-Null

$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -eq $Subject } | Select-Object -First 1
if (-not $cert) {
    Log "Creating self-signed code signing certificate: $Subject"
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -CertStoreLocation Cert:\LocalMachine\My `
        -KeyUsage DigitalSignature `
        -KeyLength 2048 `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(5)
} else {
    Log "Using existing certificate: $($cert.Thumbprint)"
}

Export-Certificate -Cert $cert -FilePath $CerPath -Force | Out-Null
Log "Trusting certificate in LocalMachine Root and TrustedPublisher"
Import-Certificate -FilePath $CerPath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
Import-Certificate -FilePath $CerPath -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null

Log "Signing catalog"
& $SignTool sign /v /fd SHA256 /s My /sm /n "CQA02303v5 Test Driver Signing" $CatPath *>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "signtool failed with exit code $LASTEXITCODE"
}

Log "Installing package with pnputil"
& pnputil /add-driver $InfPath /install *>&1 |
    Tee-Object -FilePath $LogPath -Append
exit $LASTEXITCODE
