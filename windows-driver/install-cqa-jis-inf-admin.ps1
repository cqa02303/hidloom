$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$InfPath = Join-Path $Root "cqa02303v5-jis-keyboard.inf"
$LogPath = Join-Path $Root "pnputil-cqa02303v5-jis-install.log"

& pnputil /add-driver $InfPath /install *> $LogPath
exit $LASTEXITCODE
