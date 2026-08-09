# Raspberry Pi OS early-initramfs experiment

更新日: 2026-08-07

## 現在の判断

Raspberry Pi OSを主系として維持したまま、通常userspaceより先にUSB keyboardの最小経路を起動する。
既存initramfsを直接上書きせず、対象kernelと一対一に対応するHIDloom専用imageを別名で生成し、
最初の実機試験はRaspberry Piのone-shot boot経路だけを使う。

完成packageを先に作らない。gadget-only、native入力、systemd handoffの順に効果と復旧性を証明し、
合格した場合だけ`hidloom-early-boot`として製品化する。

Upstream仕様はRaspberry Pi公式の
[`tryboot`](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#fail-safe-os-updates-tryboot)と
[`cmdline` / `initramfs` / `auto_initramfs`](https://www.raspberrypi.com/documentation/computers/config_txt.html)、
Linux kernelの[initramfs / rootfs](https://www.kernel.org/doc/html/latest/filesystems/ramfs-rootfs-initramfs.html)
を正とする。`tryboot.txt`は`config.txt`の差分fragmentではなく代替config全体として生成する。

## 目的

- 現行Raspberry Pi OS package、device profile、管理UIを維持したまま、物理keyboardの利用開始を早める。
- `systemd-analyze` totalではなく、`hidg ready`、host USB enumerate、`input-ready`、
  `usable keyboard`を主指標にする。
- Buildroot M6を置き換えず、Raspberry Pi OSとBuildrootの中間にあるhybrid方式の効果と保守負荷を測る。
- 手作業でboot imageを変更せず、cross-build host上で再生成・検証できるartifactにする。

## 対象外

初期sliceにはPython companion、HTTP、Vial、Bluetooth、OLED、LED、networkを入れない。
`LT` / `MT` / `TT`、Tap Dance、macro、text、script、analog stickなどcompanion依存の機能は、
通常systemdへhandoffした後の完全機能として扱う。初期合否は通常key、modifier、単純layer、
JIS main / US sub keyboard endpointの早期入力で判断する。

## 固定する安全境界

1. Raspberry Pi実機ではcompileしない。static ARM64 binaryとimageはcross-build hostで生成する。
2. E1のhost検証が完了するまで`<keyboard-host>`のboot領域へ書かない。
3. 最初の配置はinstalled-but-disabledとし、既定`config.txt` / `cmdline.txt`を切り替えない。
4. 最初のbootはone-shotだけにし、次回bootは既存Raspberry Pi OSへ戻る構成にする。
5. E3 chain未成立の異常はtimeout付きfail-openとし通常rootfs / systemdへ進む。chain-staged後の異常は
   二重ownerを避けるためfail closedとし、hostに残る押下状態は終端reportまたはverified UDC unbindで解消する。
6. 対象kernelのrelease、module `vermagic`、architecture、USB identity、profile hashが一致しなければ起動を拒否する。
7. 通常成功するsystemd handoffではUDCをunbindしない。descriptor、VID/PID、serial、function順が一致した時だけ
   既存gadgetをmutation-freeでadoptする。安全な終端reportを証明できない失敗時のverified UDC unbindは緊急復旧に限る。
8. early daemonと通常daemonを同時ownerにしない。early側のlive socket/status/log/runtimeは
   `/dev/hidloom-early/`へ隔離し、`/run/hidloom-early/`はroot移行後の公式証跡に使う。
   独立enableされる通常outputd/core/matrixdもprepareを強依存し、discovery/auth/release失敗後には起動させない。
9. handoff時は`matrixd`のevent受付を止め、coreの`release_all`を確認してcoreを先に停止する。core送信、outputd USB転送、
   hidd受信counterの完全一致でqueue drainを証明した後に両endpoint zeroを送り、outputd / hiddを順に停止する。
10. output targetを変更した試験は、最後に`auto`へ戻してstatusを確認する。
11. `tryboot.txt`の1行はfirmware上限98文字以内とし、通常`kernel8.img`を上書きせずalternate kernelも別名で置く。
12. `autoboot.txt`の`tryboot_a_b=1`、secure-bootの`boot.img` / `tryboot.img`経路、active `include`がある構成は初回E2の対象外として配置前に拒否する。

## 既存資産と新規実装境界

再利用するもの:

- `tools/package/build_release_bundle.sh`: ARM64 static `hidloom-hidd`、`hidloom-outputd`、
  `hidloom-logicd-core`、`hidloom-uidd`、`hidloom-usb-gadget-fast`、`matrixd`のcross-build。
- `tools/hidloom_usb_gadget_fast/hidloom_usb_gadget_fast.c`: production USB descriptorとidentity環境変数。
- `tools/buildroot_m6_runtime_smoke.py`: endpoint別startup releaseとARM runtime smoke。
- `tools/boot_marker_baseline.py` / `tools/remote_boot_baseline_collect.py`: Pi側boot markerとhealth evidence。
- `tools/usb_enumeration_watch.py`: host側enumerate時刻。
- Buildroot M6のdaemon起動順と必要runtime file inventory。

そのまま再利用しないもの:

- Buildroot M1 gadget descriptor。productionのReport ID、Raw HID、US sub endpointと一致しない。
- Buildroot用ARMv7 binary。Raspberry Pi OS v8 kernelの実験にはARM64 static binaryを使う。
- 現行gadget helperの無条件再作成経路。既存UDCをunbindするためhandoff用途には使わない。
- Buildroot M6の`initramfs disabled`設定。Buildroot自身のrootfs最小化方針であり、本実験と目的が異なる。

## 想定するboot sequence

```text
firmware
  -> Raspberry Pi OS kernel
  -> Raspberry Pi OS initramfs-tools /init + HIDloom early overlay
       -> proc/sys/dev/run/configfsを準備
       -> exact moduleをload
       -> production USB gadgetをbind
       -> hidd -> outputd -> logicd-core -> matrixd
       -> early input-ready marker
       -> real rootfsをmount
       -> matrix停止 -> core release/停止 -> queue drain -> endpoint zero -> outputd/hidd停止
  -> normal systemd
       -> gadget descriptor一致を検証してadopt
       -> normal hidd/outputd/core/matrixd/companionを起動
       -> remaining servicesを通常どおり起動
```

early processをsystemdに暗黙adoptさせない。最初の実装は短い入力停止を許容する明示handoffとし、
USB device自体は接続したまま維持する。continuous process adoptionは、明示handoffの性能が不足した場合だけ別実験にする。

## 段階計画

### E0: current state / baseline

実機変更前に次を固定する。

- kernel release、architecture、OS、boot firmware package。
- `/boot` / `/boot/firmware`の既存kernel、initramfs、空き容量。
- initramfs generator、利用可能な圧縮形式、kernelのearly-userspace関連config。
- `dwc2`、`libcomposite`、`usb_f_hid`、GPIO / gpiomem moduleのexact path、size、`vermagic`。
- core/profile package version、device profile、boot ID、failed unit、主要service、status JSON、HTTPS status。
- controlled reboot 3 samplesの`keyboard_ready`、`usb->input`、`hidd->input`。

標準採取:

```bash
make boot-report DEVICE=02
make boot-report-reboot DEVICE=02
```

3 sampleは個別artifact directoryへ保存する。reboot前後でpackage/profileとboot設定が変化していないことを確認する。

E0合格条件:

- 3 sampleすべてでfailed unit 0、pressed state 0、HID write/drop/forward error 0。
- exact kernel/moduleをhost側artifactへ取り込む方法を決定できる。
- boot partitionに既存imageを残したままalternate imageを置ける容量がある。
- rollbackが通常boot選択または次回bootで成立する。

### E1: host-only gadget image

cross-build hostで次を実装する。

- deterministic staging manifest。
- target kernel、exact base initramfs、module treeを明示入力にするbuilder。
- baseのuncompressed early-newc prefixとzstd main suffixをbyte不変で保持し、その境界へ
  deterministic overlay-newcだけを挿入するbuilder。base末尾appendとfull rootfs再packは行わない。
- 既存initramfs-tools `/init`から呼ぶidempotent `param.conf` / init-premount hook、
  `hidloom-usb-gadget-fast`、展開済みの必要module、identity snapshot、installed profile definition hash。
- `early-image.json`、file SHA-256、source commit、kernel release、module `vermagic`を含むprovenance。
- imageを展開せず検証できるverifierと、展開後rootfs verifier。
- second buildが同じcontent manifestになるreproducibility test。

E1ではkey report daemonを起動せず、gadget bind後にendpoint別zero reportだけを送る。
imageは`build/artifacts/`以下へ生成し、repositoryへbinaryをcommitしない。

E1合格条件:

- host test、shell/Python構文、descriptor comparison、ARM64/static binary、module release、file modeをpass。
- base early prefix / zstd suffixのSHA-256が入力と一致し、合成imageを`unmkinitramfs`で展開できる。
- absolute private path、credential、実IP、不要なpackage/runtimeを含まない。
- target kernel不一致、module欠落、descriptor不一致fixtureをfail closedで拒否する。
- artifact sizeとboot partition必要量を記録する。

### E2: one-shot gadget / adopt

E1合格後だけ`<keyboard-host>`へ配置する。

1. boot設定、既存image、package/healthをbackup/snapshotする。`autoboot.txt`、`boot.img` / `boot.sig`、
   active `include`、通常`config.txt` / `cmdline.txt` / kernel hashも再確認する。
2. adopterを含むfinal sourceからcore/profileを同じversionでcross-buildし、同じAPT transactionで導入する。
   profile適用後のnormal gadgetをread-only captureし、package/version、installed profile definition、helper、
   identity、descriptor、UDC、function/dev mapping、configfs static snapshotをE1 manifestの`adopt`契約へ追加する。
3. exact alternate kernel、alternate initramfs、accepted manifest、完全な`tryboot.txt`をhostでstage/verifyし、
   rootfs accepted manifestは`/var/lib/hidloom/early-boot/early-image.accepted.json`へ、boot payloadは
   `/boot/firmware`へdisabled配置する。通常kernel、`config.txt`、`cmdline.txt`は変更しない。
4. 現行`cmdline.txt`を別名へ複製して`hidloom.early=e1 panic=10`を追加し、`tryboot.txt`から
   `cmdline=<alternate-file>`で選ぶ。通常`cmdline.txt`は変更しない。
   `panic=10`はkernel panic時に次の通常bootへ戻す補助であり、tryboot one-shot flagの代替ではない。
5. one-shot bootを1回実行し、early marker、host enumerate、通常systemd到達を確認する。
6. normal gadget unitはearly manifestを検証し、同一gadgetなら再作成せずadoptする。markerなしfresh boot、
   またはmarkerなし・UDC empty・二重snapshot不変のnormal restart residueだけ従来createを許可する。
7. 次回通常bootでalternate経路を使っていないことを確認する。

E2では自動文字入力を行わない。main / US sub endpointへzero reportを送るだけにする。

E2合格条件:

- early gadget bindとhost enumerateを確認できる。
- handoff中のUDC unbind、USB disconnect、二回目のenumerateが0。
- 通常systemd、SSH、HTTPS、全healthが復旧する。
- one-shot失敗時に次回通常bootへ戻れる。

#### E2固定実行手順

実行順序は次で固定し、途中の成果物を後段の入力として使う。`<source>`、`<version>`、
`<artifact>`、`<stage>`、`<backup>`は実行記録へ実値を残す。device上でcompileしない。

1. host gateを通したsourceをcommitし、そのcommitだけからcore/profileをcross-buildする。

   ```bash
   python3 script/test_rpi_os_early_initramfs_tool.py
   python3 script/test_rpi_os_early_tryboot_tool.py
   python3 script/test_rpi_os_early_tryboot_place_tool.py
   python3 script/test_rpi_os_early_gadget_adopt_tool.py
   python3 script/test_rpi_os_early_gadget_handoff_wrapper.py
   python3 script/test_validation_suite.py
   make core-deb-package
   make DEVICE_PROFILE=keyboard-ver1 profile-deb-package
   tools/package/release_candidate_check.sh --split-profile keyboard-ver1 --skip-validation
   ```

2. `<keyboard-host>`のpackage、profile、health、通常boot 4 fileをsnapshotし、旧core/profile `.deb`を
   `<backup>/rollback-debs/`へ保存する。APT simulationで対象2 packageだけの更新を確認した後、
   core/profileを同一APT transactionで導入してprofileを適用する。

   ```bash
   sudo apt-get -s install /tmp/hidloom-core_<version>_arm64.deb \
     /tmp/hidloom-profile-keyboard-ver1_<version>_arm64.deb
   ```

   simulation後、actual直前に`/proc/meminfo`、`dpkg --audit`、APT / dpkg / mandb process、
   package-manager lock holderを採取する。Pi Zero 2 Wの初期fail-closed値は
   `MemAvailable >= 128 MiB`、`SwapFree >= 256 MiB`かつ`SwapTotalの75%`とする。いずれかを満たさない場合、
   `swapoff`でzramを無理に解放せずactualを開始しない。clean reboot後にcandidate checksum、package state、
   audit、simulation、memory gateを取り直す。

   cross-build hostのrepositoryからread-only gateをstdinで実機へ渡し、stdoutのJSONを実行証跡へ保存する。

   ```bash
   ssh <device> 'python3 -' < tools/package/low_memory_install_preflight.py
   ```

   `ready=true`かつ終了code 0の場合だけ次へ進む。toolはpackage install、service停止、lock取得、swap変更を行わない。

   gate合格後だけactualとprofile applyを別々のremote commandで実行する。

   ```bash
   sudo apt-get install -y /tmp/hidloom-core_<version>_arm64.deb \
     /tmp/hidloom-profile-keyboard-ver1_<version>_arm64.deb
   sudo hidloom-profile keyboard-ver1 --apply --backup --restart
   ```

   APTとprofile適用は別々のremote commandとして実行し、開始時刻とboot IDを記録する。APTが
   60秒以上無出力になった場合は最終表示だけからtrigger停止と断定せず、別sessionでAPTのRSS / swap / wchan、
   `free`、`/proc/meminfo`、zram `mm_stat`、process / lock、APT / terminal / dpkg log、kernel OOM / MMC / EXT4を
   最小限採取する。SSH bannerもtimeoutする場合は確立済みsessionを切断せず30分待つ。非TTY sessionへ
   signalを送る、`dpkg`を直接killする、電源断する操作は行わない。
   到達性が戻ったら、追加installやprofile適用より先にAPT / `dpkg` processとlock、`free` / `vmstat`、
   kernelのOOM / MMC / EXT4 log、APT history / terminal / dpkg log、`dpkg --audit`をread-only確認する。
   package / triggerがinstalled、process / lockなし、audit cleanならtransactionを再実行しない。
   lock解放後にpending triggerがある場合だけ`sudo dpkg --configure -a`、dependency不整合がある場合だけ
   memory gate合格後に`sudo apt-get -f install`で修復し、auditがcleanになってからprofile適用へ進む。
   30分で戻らない場合はboot payloadを配置せず停止し、
   consoleからのclean rebootまたは明示した物理復旧を別判断にする。

   profile適用後、core/profileのversion/source/architecture一致、failed unit 0、主要service active、
   pressed state 0、HID error 0、HTTPS status、output `auto`を確認する。

3. installed helper、installed profile definition hash、exact kernel/module、通常initramfs、USB identityを入力にして
   `<artifact>/e1-final/`へE1 imageを2回生成する。2回のimage/manifest byte一致とdeep verifyを再確認する。

4. E1 manifestをdevice上のroot所有temporary directoryへ置き、稼働中のnormal gadgetからaccepted contractを
   read-only captureする。次の引数をproduction値として固定する。

   ```bash
   sudo /usr/bin/python3 -S /usr/lib/hidloom/tools/rpi_os_early_gadget_adopt.py capture \
     --manifest <root-owned-e1-manifest> --output <new-accepted-manifest> \
     --core-package-name hidloom-core \
     --profile-package-name hidloom-profile-keyboard-ver1 \
     --configfs-root /sys/kernel/config/usb_gadget \
     --proc-root /proc --sys-root /sys --dev-root /dev --package-root / \
     --profile-root /usr/share/hidloom/profiles \
     --runtime-profile-marker /mnt/p3/device_profile.json \
     --helper /usr/lib/hidloom/bin/hidloom-usb-gadget-fast
   ```

5. accepted manifestをcross-build hostへ戻し、通常`config.txt` / `cmdline.txt`、exact `kernel8.img`、
   final E1 imageから`<stage>`を作る。stageはboot領域外で生成し、独立verifyする。

   ```bash
   python3 tools/rpi_os_early_tryboot.py stage \
     --config <normal-config> --cmdline <normal-cmdline> \
     --e1-image <final-e1-image> --e1-manifest <accepted-manifest> \
     --kernel-image <exact-kernel8.img> \
     --kernel-image-name kernel8-hidloom-e1.img --output-dir <stage>
   python3 tools/rpi_os_early_tryboot.py verify --directory <stage> \
     > <artifact>/e2-stage-verify.json
   ```

6. `<stage>`をdevice上のroot所有0755 directoryへ、全fileを0644でcopyする。配置helperの
   `preflight`、`install-disabled`、`verify-installed`を同じ引数で順に実行する。

   ```bash
   sudo /usr/bin/python3 -S /usr/lib/hidloom/tools/rpi_os_early_tryboot_place.py preflight \
     --stage-dir <root-owned-stage> --boot-root /boot/firmware \
     --accepted-root /var/lib/hidloom/early-boot --backup-dir <new-backup> \
     --normal-initramfs-name initramfs8 \
     --model-path /sys/firmware/devicetree/base/model \
     --expected-model 'Raspberry Pi Zero 2 W Rev 1.0' \
     --kernel-release-path /proc/sys/kernel/osrelease \
     --expected-kernel-release <exact-release> \
     --expected-placement-sha256 <e2-stage-verify.jsonのplacement_sha256>
   ```

   `expected-placement-sha256`は単独の`sha256sum`ではなく、hostのdeep verifyがpassして返した値を使う。
   device側はこの値へmanifestをpinし、全stage fileと通常boot inputをbounded streaming hashで照合する。
   E1 initramfsをdevice上で再展開しない。`install-disabled`と`verify-installed`も上と同じ引数を使う。
   合格時も通常`config.txt`、
   `cmdline.txt`、`kernel8.img`、`initramfs8`のhashが配置前と同じこと、receiptが
   `default_boot_modified=false` / `one_shot_requested=false`であることを別途確認する。

7. disabled配置のhealthを確認し、OTG/data USBを観測用hostへ接続する。通常gadgetがhostに列挙され、
   deviceのUDCが`not attached`ではないことを確認してからWindows側のenumeration watcherを開始する。
   host接続またはwatcherを準備できない場合はone-shotを実行しない。pressed state 0、HID error 0、
   output `auto`を確認してから、一度だけ次を実行する。このcommand以外からtrybootをactivateしない。

   Windows側watcherはdevice/driverやtargetを変更しないread-only helperを別terminalで起動する。
   現candidateのVID/PIDは明示引数にし、`WATCHER_READY`、baseline 3 selector readyを確認してからrebootする。
   watcherはbounded PnP instance operation subscriptionを先にarmし、正規化した3つのexact HID child
   prefixだけを判定する。USB parent、部分一致、別deviceのeventは合否に使わず、対象childのdeletionは
   snapshot間でremove/re-addが完了した場合もdisconnectとして扱う。

   PnP観測はCodex `CodexSandboxOffline` contextではなく、native Windows管理者PowerShell 5.1から実行する。
   generated operator wrapperは実行前にPowerShell 5.1 parserへ通し、colon直前の変数は`${Mode}`のように区切る。
   `Get-FileHash`だけに依存せず.NET SHA-256 fallbackを持ち、case-insensitiveな自動変数`$PID`と衝突する
   `$Pid`をparameter/local名に使わない。mandatory parameterへ初期状態の空`ArrayList`、event list、空文字を含む
   Markdown line listを渡す経路には`AllowEmptyCollection` / `AllowEmptyString`を明示する。parser、hash、binding、
   PnP permissionのいずれかが失敗した場合は`WATCHER_READY`未到達として、target rebootを行わずfresh bundleでやり直す。

   最初に5秒のruntime gateを実行する。deviceをrebootしないため終了code 21 /
   `initial_disconnect_not_observed`が期待値であり、bundle内のbaseline / final readyと
   `target_operation_before_ready_zero=true`を確認する。終了code 20または70、baseline不足、report bundle不足なら
   one-shotへ進まない。runtime gateと本番watchは異なる`OutputPrefix`を使い、同じVID/PIDの別deviceは外す。
   以下の`RunId`とdirectoryは実行ごとに新しくし、既存bundleを再利用または上書きしない。

   ```powershell
   $RunId = Get-Date -Format 'yyyyMMddTHHmmss'
   $WatchRoot = ".\build\artifacts\rpi-os-early-e2-windows-watch\$RunId"
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\windows_usb_enumeration_watch.ps1 `
     -VendorId 1D6B -ProductId 0105 -DurationSec 5 -PollIntervalMs 200 `
     -OutputDirectory $WatchRoot -OutputPrefix "e2-watcher-runtime-gate-$RunId"
   ```

   runtime gate合格後、新しいbundle名で120秒watchを開始する。literal `WATCHER_READY`が出るまでrebootしない。

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\windows_usb_enumeration_watch.ps1 `
     -VendorId 1D6B -ProductId 0105 -DurationSec 120 -PollIntervalMs 200 `
     -OutputDirectory $WatchRoot -OutputPrefix "e2-one-shot-$RunId"
   ```

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 <device> "sudo -n reboot '0 tryboot'"
   ```

8. one-shot commandはSSH切断や終了codeにかかわらず消費済みとして扱い、再実行しない。SSH復帰後、通常rebootより
   先にboot ID、`/proc/cmdline`、`/run/hidloom-early/`、gadget UDC、service journal、package/profile、
   failed units、主要status JSON、HTTPS、host enumerateを採取する。remote collectorには
   `--reboot-before-sample`を付けない。collectorの終了code 0は採取成功であってhealth合格ではないため、
   one-shot boot IDの変化、`hidloom.early=e1` / `panic=10`、canonical early marker、running kernelとaccepted
   runtime contractの一致、mutation-free adopt marker、accepted / receipt hash、UDC、package/profile/healthを
   個別に確認する。通常rebootはephemeral evidenceのcopy完了後かつWindows watcher終了後まで行わない。

   ```bash
   python3 tools/remote_boot_baseline_collect.py <device> \
     --label <one-shot-label> --samples 1 --sudo \
     --output-dir <artifact>/one-shot-device \
     --remote-dir /tmp/<unique-one-shot-collector-dir>
   ```

   次に別のWindows watcher bundleを開始して`WATCHER_READY`を確認し、通常rebootを1回だけ実行する。SSH復帰後も
   rebootなしcollectorで別directoryへ採取し、`hidloom.early=e1`と`/run/hidloom-early` / adopt markerがなく、
   通常boot 4 hash、disabled placement、package/profile、output `auto`、healthが復旧したことを確認する。

   ```bash
   ssh -o BatchMode=yes -o ConnectTimeout=10 <device> 'sudo -n systemctl reboot'
   # wait for SSH to become reachable before collecting; do not request another reboot
   python3 tools/remote_boot_baseline_collect.py <device> \
     --label <normal-fallback-label> --samples 1 --sudo \
     --output-dir <artifact>/normal-fallback-device \
     --remote-dir /tmp/<unique-normal-fallback-collector-dir>
   ```

   Windows watcherはbaseline present、initial disconnect、first re-add ready、post-first-ready disconnect 0、
   final ready、`target_operation_before_ready_zero=true`をすべてpassしたbundle内の`report.json` / `report.md`と
   終了code 0を証跡にする。one-shot / normal fallbackの両watcherと全device assertionがpassした時だけE2合格とする。

one-shot後にSSHへ到達しない場合は電源を入れ直す。firmwareはtryboot flagを起動前にclearするため、次回は通常
`config.txt`へ戻る。SSHへ到達したがgadget adoptだけがfail closedした場合も、alternate fileを変更せず通常rebootする。
package rollbackが必要なら`<backup>/rollback-debs/`の旧core/profileを同一APT transactionで戻し、
`hidloom-profile keyboard-ver1 --apply --backup --restart`と通常healthを再確認する。

### E3: native early input

次の順で一つずつ追加する。

1. `hidloom-hidd`
2. `hidloom-outputd` (`target=usb`)
3. `hidloom-logicd-core`
4. `matrixd`

initramfs-toolsは`/dev`をreal rootへ先にmoveし、`/run`をその後にmoveする。したがってpathname socketを
旧`/run`から持ち越さない。early daemonのlive socket/status/log/runtimeはmove済みdevtmpfs上の
`/dev/hidloom-early/`へ置き、公式ready、runtime contract、4-field PID記録、handoff証跡だけを
`/run/hidloom-early/`へ置く。PID記録は`pid starttime exe_dev exe_ino`を0600で固定する。
runtime keymap/configはmanifestでhashを固定し、通常rootfsのmutable fileをearly boot中に暗黙参照しない。

`tools/rpi_os_early_initramfs.py build`のE3拡張は、hidd/outputd/logicd-core/matrixd、keymap/keycodes、
logicd/matrixd config、exact `raspberrypi-gpiomem.ko`の9入力をall-or-noneで受ける。4 daemonは
ARM64 static ELF、matrixd configはGPIO有効かつ`/dev/hidloom-early/matrix-events.sock`、moduleは
exact kernel ABIでなければbuildを拒否する。起動順はhidd -> outputd -> logicd-core -> matrixdで、
各readyをboundedに確認する。E4で既にzeroだったendpointにも新しいzero writeを証明するため、E3 hiddだけ
`USBD_KEYBOARD_REPORT_DEDUP=0`とし、この条件をnative input contractへ固定する。通常systemd hiddのdedupは変更しない。
native build/verifyはhook/launcherが使う16個の絶対commandをbase newc内で解決し、symlink、cpio hardlink payload、
実行modeを検証する。init-bottom hookは`setsid`直後のnumeric leader / negative PGID成立をboundedに待つ。
timeout cleanupではleaderとgroupの双方を監視し、残存時はverified UDC unbind後に両方を停止する。
全producer消滅を証明する前のdirect endpoint zeroは終端reportとして扱わない。

host gateは`tools/rpi_os_early_native_smoke.py`で実ARM64 static binaryをQEMU起動し、startup release、
LSFT+A+F overlap、JIS main `KC_RO`、US sub `KC_A`、最終pressed/injected/modifier 0とsplit route clearを確認する。

E3合格条件:

- startup releaseがmainはReport ID付き9 bytes、US subはReport IDなし8 bytesである。
- 通常key、modifier、overlap入力の自動smokeがpressed state 0で終了する。
- 実keyのinput-to-HID markerとhost到達を確認できる。
- early入力が失敗しても通常systemd側の完全機能へ復旧する。

### E4: release-safe systemd handoff

handoff順序を固定する。

1. `hidloom-early-input-handoff-prepare.service`をUSB gadgetより前に必ず実行する。path Conditionは使わず、
   valid E3 markerがなければhelper自身が`not-applicable`を返す。
2. runtime contract hashと4 daemonのPID/starttime/executable device+inode/path/UIDを全件認証し、各processを
   `pidfd_open`へ固定する。4 status PIDと固定topologyを照合し、hidd/outputd/coreのpathname socketは
   `/proc/net/unix`のkernel inodeからprocess FD ownerへ、hidg0/hidg2はcharacter nodeからhidd FDへ結合する。
   停止signalと終了待ちはpidfdだけを使い、一件でも不明なら未認証PIDにはsignalを送らずexit 78でfail closedする。
   ただしhostの押下状態を残さないため、bound gadgetはverified UDC unbindで切断する。
3. matrix event受付を停止する。
4. logicd-core control socketへ`release_all`を送り、pressed matrix/key/injected/modifierと全split routeが0を確認する。
5. logicd-coreを停止して唯一のproducerを消滅させる。core `broker_frames_sent`、outputd `frames_received` / `frames_to_usb`、
   hidd `frames_received`の完全一致と、uinput/BT/error/control/release counter 0を確認する。live producer中の一時的一致は採用しない。
6. outputd control socketへ`release_all`を送り、main/US-subのattempted=2 / delivered=2 / errors=0とrelease/control counterの
   exact増分を確認してoutputdを停止する。その後hidd受信数のexact `core+2`と両zero-report counterの各+1以上を確認する。
7. hiddを停止し、全PID identity消滅後にcounter equationを含む0600のprepare証跡を書く。
8. normal USB unitが同じconfigfs gadgetをmutation-free adoptし、hidd/outputd/core/matrixdを起動する。
9. matrixdからpullされる`hidloom-early-input-handoff-finalize.service`が通常4 statusのPID/executableと
   socket/endpoint ownerを同じ方法で確認し、prepareとは別のcomplete証跡を書く。logicd-coreは最初のreport前には
   正常でも`broker.available=false`なので、authenticated outputd routeとerrorなしをready条件にし、通信発生を要求しない。

通常のprepare成功経路はconfigfs/UDCを変更せず、終端reportとPID停止を証明した後にmutation-free adoptへ進む。
認証後にactionが失敗した場合は、認証済みpidfdでmatrixd / logicd-core / outputd / hiddを順序停止し、
全daemonの終了後にmain 9 bytesとUS sub 8 bytesのexact terminal reportを書く。daemon終了または両reportを
証明できなければverified UDC unbindでhostを切断する。chain-staged discoveryまたは認証の失敗は
未認証PIDに触れずverified UDC unbindを行う。どちらも上書き不可の0600 failure evidenceを残し、
normal USBを開始せず次回の通常fallback rebootで復旧する。markerなしの通常bootとE3 chain未成立bootは
fail-openでnormal chainへ進む。

物理key押下中、modifier押下中、companion delegated key押下中も試験する。SIGTERMだけをrelease保証にせず、
control responseとfinal statusを合否証跡にする。

### E5: performance / stability decision

自動確認:

- controlled reboot 10回。
- boot marker、USB watcher、package/profile、failed units、service restart counter、status JSON。
- HID native live smoke、held-key handoff、JIS/US split、endpoint reopen、Vial Raw HIDの通常boot後回帰。
- fail-open fixture: module欠落、profile hash不一致、early daemon timeout。

operator確認:

- cold boot 3回のCtrl / Shift / Alt非固着。
- 安全な入力欄で通常key、modifier、JIS/US sub、roll/overlap。
- handoff前後でUSB接続音やdevice消失がないこと。
- 通常boot後のLT、Vial、OLED、LED、analog stick、shutdown。

製品化のgo条件:

- 同じdevice/host条件の`input-ready`中央値がbaseline比25%以上かつ2秒以上短い。
- handoffによるUSB再enumerate 0、stuck key 0、failed unit 0、HID error 0。
- 10 controlled rebootと3 cold bootを完走する。
- 通常Raspberry Pi OSとone-shot fallbackが再現する。

効果が小さい、image load時間が支配的、handoffが不安定、kernel update保守が重すぎる場合は、
package化せず実験artifactとして終了する。

### E6: optional package

合格時だけ次を追加する。

- `hidloom-early-boot` control package。
- exact kernel/source/profileに固定したimage packageまたはartifact。
- `build`、`verify`、`status`、`try-once`、`enable`、`disable`、`rollback` command。
- install時disabled、明示enable、atomic backup、boot space preflight。
- kernel更新時は自動で重いbuildを行わず、version mismatchを検出してearly bootをfail closedにするguard。
- cross-build hostで新kernel用imageを再生成してから切り替えるrunbook。

packageのpostinstはdefault bootを自動切替しない。remove/upgrade時も既知正常imageと通常bootを残す。

E6の標準buildは、review済みE3 disabled placementから回収した`receipt.json`、`boot/`、`accepted/`を
source tree外またはignored artifact directoryへ置き、x86_64 Linux/WSL cross-hostで行う。

```bash
tools/package/build_early_boot_deb.sh \
  --payload-root build/artifacts/<candidate>/payload \
  --version 0.0.<rev>+git<sha> \
  --out-dir build/artifacts/<candidate>/package \
  --work-root /tmp/hidloom-early-boot-deb-work
dpkg-deb --info build/artifacts/<candidate>/package/hidloom-early-boot_*_arm64.deb
dpkg-deb --contents build/artifacts/<candidate>/package/hidloom-early-boot_*_arm64.deb
```

targetではcore/profileのexact同versionを先に確認する。installはdisabledで、postinst後にboot IDと
`config.txt` hashが不変であることを確認してから操作する。

```bash
sudo dpkg -i hidloom-early-boot_<version>_arm64.deb
sudo hidloom-early-boot verify --live
sudo hidloom-early-boot status
sudo hidloom-early-boot try-once --confirm-source <full-source-sha>          # rebootしないcommand gate
sudo hidloom-early-boot disable --reason non-reboot-command-test
sudo hidloom-early-boot enable --confirm-source <full-source-sha>            # 次bootからpersistent
sudo hidloom-early-boot disable --reason operator
sudo hidloom-early-boot rollback
```

`try-once --reboot`、persistent enable後のreboot、normal fallback rebootは、各回fresh dynamic prefixの
Windows watcherがliteral `WATCHER_READY`を出した後だけ1回送る。reboot送信結果にかかわらず再送しない。
kernel package postinstはimageをbuildせず、pinned releaseと異なる時にenabled configをnormalへ戻す。
新kernelへ進む時はtargetでbuildせず、cross-hostで新しいexact kernel/initramfs payloadを生成・deep verifyし、
新versionのpackageをinstall-disabledで配置してE2-E6 gateを繰り返す。remove/upgrade前は`status=disabled`を必須とし、
既存boot payloadとnormal configのhashを比較する。

## Evidence layout

```text
build/artifacts/rpi-os-early-initramfs-<source>-<timestamp>/
  e0-preflight/
  e0-baseline-01/
  e0-baseline-02/
  e0-baseline-03/
  e1-build/
  e1-verify.json
  early-image.json
  SHA256SUMS
  e2-tryboot/
  e3-input/
  e4-handoff/
  e5-soak/
```

各実機結果にはcommand、device、package/profile version、kernel、source commit、pass/fail、boot ID、
rollback stateを記録する。実行結果は`real-device-test-checklist.md`、区切りの要約は`CURRENT_STATUS.md`、
残作業は`TODO_PRIORITY.md`へ反映する。

## 現在の進捗

| phase | 状態 | 次のaction |
| --- | --- | --- |
| E0 | pass | `<keyboard-host>` read-only preflightと3 reboot baselineを2026-08-05に完了 |
| E1 | pass | exact inputの2回生成、negative fixture、deep verifyを2026-08-05に完了 |
| E2 | pass | 初回`cdadc2bcd`の`bMaxPacketSize0` fail closedをsnapshot v2で限定修正し、source `0ebc76ddb`のWindows v4 runtime gate / one-shot / normal fallback、mutation-free adopt、rollbackを2026-08-06に完了 |
| E3 | pass | source `3e7ab2b10`のone-shot inputとWindows host fresh normal-fallback watcher、最終healthをpassした。現keymapにmain-special `KC_RO`割当がないためmain nonzero実入力はN/A |
| E4 | pass | exact handoff counter、両endpoint release、early retire、normal single owner、mutation 0、Windows handoff/fallback後disconnect 0をpassした |
| E5 | pass | controlled reboot 10、Windows watcher付きreboot 10、cold boot watcher 3、独立cold boot modifier非固着3、operator入力/目視、shutdown/rollback、最終package/HID/Vial health、E0比9.631秒 / 約65.6%短縮をpass |
| E6 | pass | exact package、disabled install、command/space/kernel guard、persistent enable/fallback watcher、remove/reinstall、final smokeを2026-08-08に完了 |

### 2026-08-07 E3-E4 pre-activation evidence

source `3e7ab2b101fc5f7d102a640ae2b74c60c0146426`のcanonical validation 235 entrypointと独立監査をpassした。
x86_64 build hostでcross-buildしたcore/profile `0.0.2045+git3e7ab2b10`をtargetへ同一APT transactionで導入し、
`keyboard-ver1`のapply、package verifier、service/status/HTTPS、failed unit 0、output `auto`をpassした。package SHA-256は
core `35df1a6e81e4f84baa7a5e10f3a1838c17279cc59720cb33822db6151b72461f`、profile
`365e53ac2c1b7ce9ebe83b0128a8b6fcc4c25a34253de0b3013b363773f2bd6c`である。

live normal initramfs basename `initramfs8`を保持したexact inputからE3 imageを2回生成し、image/manifest byte一致、
deep verify、ARM64 QEMU chainをpassした。imageは26,205,035 bytes / SHA-256
`255f294ae7eb79858406eec35c4297856650c697084cccc78aa0067ea461c47c`、manifest SHA-256は
`50fc76d7569f06f020e44fc6c59a79663ba04bb641a64e23fe646cd507d8b87b`。最初のbyte-identical input copyは
basenameが`base-initramfs8`だったためdevice preflightが配置前に拒否し、正しいbasenameで再生成・再検証した。
normal gadgetのread-only captureはconfigfs mutation 0、accepted manifest SHA-256
`45ce4d67d63faf34504063300fdcccc936e61a3af1d3b4950d7f5014eaeeb59e`。host stageのplacement SHA-256は
`a50ff0a9cc96a00c4a56d6b6fbd359c4cd5b72558915e760472fe722e2e081cc`である。

旧E2はinstalled contentをexact verify後、checksum付きbackup
`/var/backups/hidloom/e2-before-e3-3e7ab2b10-20260807T021625Z`、boot payload quarantine
`/boot/firmware/.hidloom-e2-retired-before-e3-3e7ab2b10-20260807T021625Z`、accepted/receipt quarantine
`/var/lib/hidloom/early-boot-retired/e2-0ebc76ddb-before-e3-3e7ab2b10-20260807T021625Z`へrecoverableに退避した。
E3はdevice `preflight` / `install-disabled` / `verify-installed`をpassし、通常boot backupは
`/var/backups/hidloom/rpi-os-early-e3-placement-3e7ab2b10-20260807T021625Z`。receipt SHA-256は
`1e66927e6245d93295925fb53191e79131a5befc1d86ec651e2d065fd7108f37`で、`status=installed-disabled`、
`default_boot_modified=false` / `one_shot_requested=false` / `reboot_requested=false` /
`tryboot_published_last=true`を確認した。boot ID `749a1fad-577a-4bd5-8c7e-d1be8ecfbd04`と通常boot 4 hashは不変で、
このpre-activation時点ではtryboot / rebootを実行していない。Windows非接続時のUDC `not attached`は期待状態であり、
E3 native実入力、E4実handoff、Windows無再列挙、通常fallbackは未判定だった。evidenceは
`build/artifacts/<keyboard-host>-rpi-os-early-e3-3e7ab2b10-20260807T021625Z/`と
`build/artifacts/<keyboard-host>-e3-e4-deploy-3e7ab2b10-20260807T020718Z/`。

### 2026-08-07/08 E3-E4 one-shot / fallback handoff evidence

source `3e7ab2b101fc5f7d102a640ae2b74c60c0146426`、core/profile
`0.0.2045+git3e7ab2b10`のままtrybootを一度だけ消費し、one-shot boot ID
`296462dd-672e-4e6b-8eb6-6b8b3305ddb5`へ到達した。early gadget readyは2.260秒、native input readyは
5.050秒、normal gadget adoptは16.114秒、normal input readyは16.558秒だった。実入力はA+LSFTをUS-subへ送り、
handoff後もpressed/error 0を確認した。現keymapにはmain-special `KC_RO`の割当がないため、main routeのnonzero実入力は
今回の物理試験ではN/Aとし、割当を一時変更してまで試験していない。

E4のprepare / complete evidenceはいずれも成立した。core送信、outputd受信、outputd USB送信、handoff前hidd受信は
すべて3、handoff後hidd受信は5で、outputd releaseはattempted / delivered / errors = 2 / 2 / 0だった。
main zero counterは1から2、US-sub zero counterは1から3へ増加し、error counterは0。early 4 processは停止し、
normal hidd/outputd/logicd-core/matrixdは各single owner、configfs mutationは0、UDCは`configured`だった。
Windows one-shot watcherはexit 0 / `reason=pass`で、全checkとMI_00&COL01 / MI_01 / MI_02のbaseline / final selectorが
ready、first re-add後のtarget disconnectは0だった。device / ephemeral evidenceは
`build/artifacts/<keyboard-host>-rpi-os-early-e3-one-shot-3e7ab2b10-20260807T124500Z/`に保存した。

その後のcontrolled normal fallbackはboot ID `0d059889-6b87-447b-870c-2497bf89cab5`でdevice側をpassした。
early token/treeはなく通常boot 4 hashは正しく、`keyboard_ready` 14.666秒、`usb->input` 0.686秒、
`MemAvailable`は約171 MiBだった。一方、Windows fallback watcherは固定output bundle
`e3-normal-fallback-20260807T125000Z`が既に存在していたためatomic publishを拒否し、exit 70となった。
これはdevice failureではないがWindows合格証跡には使わない。E3/E4 closeoutはWindows execution hostを実行主体として、fresh unique
watcherをarmしてから通常rebootをもう1回だけ行い、exit 0 reportとdevice healthを同一runで回収するまで未完了とする。
実行境界とfail-closed手順はprivateの private workspace reference *(omitted from public export)* を正とする。

E0の3 sampleは`keyboard_ready` 13.690 / 14.681 / 15.076秒、`usb->input`
1.599 / 1.776 / 2.077秒で、`keyboard_ready`中央値は14.681秒だった。kernelは
`6.18.34+rpt-rpi-v8`、core/profileは`0.0.2032+gitf7ce84c4e`、全sampleでfailed unit 0、
pressed state 0、HID error 0を確認した。証跡は
`build/artifacts/rpi-os-early-initramfs-4c4c830f53f0-20260805T113854Z/`に保存した。

現行normal gadget helperは起動時に既存gadgetを無条件unbind / 削除して作り直すため、そのままE2へ進むと
USB再enumerateが発生する。E2 host gateではservice専用wrapperと3値adopterを追加した。early markerと
accepted manifestが存在する時だけconfigfsをread-only検査し、完全一致ならadopt、不一致なら既存gadgetを
変更せずfail closedにする。marker/gadgetともない通常bootと、markerなし・UDC empty・二重snapshot不変の
normal restart residueだけ従来createへ進める。tryboot stageとdisabled-placementのhost fixtureもpass済み。

E1 imageは23,724,907 bytes、overlayは936,448 bytes、SHA-256は
`777c2d6009f97d46753efabb140a5c5d1ea0f8a8cefc7bd71b9122979c1d0612`。2回のbuildでimageと
manifestがbyte一致し、元imageのearly prefix SHA-256
`d5fd5fa350187b87ac59488fa2edeae81145f2ebe3a0f6975659a09d76005f49`とzstd suffix
`ba532d98b0b1ea8c233d68d36939dd3c569be7cda964a93d6b4ef480adb0f6e1`を保持した。
このE1 artifactはhost gate証跡であり、E2配置前にはadopterを含むcommitted package sourceと
更新後のinstalled profile definition hashで再生成する。

2037 package actual前は`MemAvailable=89 MiB` / swap free 168 MiBで、画面上は`man-db`を最後に
user-space応答が止まった。復旧後の保存logではcore/profileと`man-db`は23:36:50までに正常完了し、
約95分後にswap free 0の状態で残存`apt-get`がOOM victimになったことを確認した。MMC / I/O / EXT4 errorはなく、
電源再投入後はpackage/audit/verify、profile、service/status/HTTPS、output `auto`、通常boot hashをpassした。
このため固定手順へactual直前memory gateとaudit clean時の再実行禁止を追加した。

source `cdadc2bcd`のinstalled core/profile `0.0.2037+gitcdadc2bcd`とexact boot inputから生成したfinal E1は
23,724,907 bytes、SHA-256
`ad7cc95005b314d822f48c26195f4981cbaa90fe49a881399ad8c361ca25a66b`で、2回buildとdeep verifyをpassした。
normal gadgetのread-only captureからaccepted manifest SHA-256
`c0f28892bb7a43de53cea55cadf4d8569fb68120af5bf9a8fe983d48ec685f1a`を作成し、6 file / 33,913,492 bytesの
stageをplacement SHA-256 `6221de7e468f5010008a7a865e33c07a218bc99bd661c33b9cbc1bf3984311bc`へpinした。
`<keyboard-host>`では`preflight`、`install-disabled`、`verify-installed`をpassし、通常boot 4 file不変、
`default_boot_modified=false` / `one_shot_requested=false`で配置した。

2026-08-06の初回one-shotではpreflight boot ID `84be2899-3caa-4e74-9f01-eb2cb3b5e2aa`から
`reboot '0 tryboot'`を一度だけ実行し、boot ID `e2750320-4852-4257-934b-e1a2d6d2a56b`、
`hidloom.early=e1 panic=10`、early ready 3.160秒、UDC `configured`を確認した。Windows watcherは
baseline ready、initial disconnect、3 selectorのfirst re-add、post-first-ready disconnect 0、final readyを満たしてexit 0。
report JSON / Markdown SHA-256は
`eff70bc5afb0a35f80b682f6db8ff4b3f4fcd6c7745f5852421433b3a6544b4c` /
`cab0bbde2510ec7c383f8127df41bf4aeca803a78c3170de59b321364adce016`だった。

device側ではaccepted manifestがpre-bind `bMaxPacketSize0=0x00`を固定していた一方、kernel / UDC bind後のlive値は
`0x40`へ正規化され、normal adopterが`changed=bMaxPacketSize0`をexit 78でfail closedした。
gadget/UDCはbound / `configured`を維持したが、`hidloom-usb-gadget.service`はfailed、依存する
`hidloom-hidd.service`はinactiveとなったためE2は不合格とした。ephemeral evidence回収後にfresh Windows watcherで
通常rebootを1回実行し、fallback boot ID `c0e63dd9-5ce0-4c9d-b613-d2e72f6f00e4`、early token/treeなし、
failed unit 0、全主要service、通常boot 4 hash、output `auto`へ復旧した。fallback watcherもexit 0で、JSON / Markdown
SHA-256は`c7178d896d9cdc8f13dd60974f2541da4ed065055670314ee7d7e4eb79394912` /
`0e9339a2de089b1780679d4cff6ce4fd1a56b070f28c08e66ca1ae7ad9fee93d`。

preflight / one-shot / fallbackの`MemAvailable`は約176,792 / 179,452 / 179,348 KiB、zram usedは
872 / 0 / 0 KiBで、one-shot/fallbackにOOM記録はない。`bMaxPacketSize0`だけをregular-file /
valid-value検査付きvolatile entryとするconfigfs snapshot v2を実装し、`0x00 -> 0x40`のnormalizationと
欠落/不正値/別static field変更のhost回帰をpassした。旧v1はfail closedで拒否する。この初回候補の時点では
修正版source/package、accepted manifest、E1/stageを再生成して同じone-shot/fallbackを再試験することを次actionとした。
evidenceは`build/artifacts/<keyboard-host>-rpi-os-early-e2-cdadc2bcd-20260805T143145Z/night-one-shot-20260806T110131Z/`。

上記初回failureを履歴として保持したうえで、source `0ebc76ddb`、core/profile
`0.0.2043+git0ebc76ddb`のcorrected candidateを再生成した。E1 imageは23,724,907 bytes / SHA-256
`60d71590745cc1e896efac8bd97516f8fe61d883b65175b5e5425b4ad5e40f7e`、accepted manifest SHA-256
`f0eeb2eef76f0ba10439cd7690012c0d6de1948bb1f95c1e52b6e665a2a0a322`、runtime contract SHA-256
`64dcd69f5aa98d73113808634ea554eacd7e6bf1431bfa5c19a55eef16e58845`、placement SHA-256
`211686a4066589f648207ab3861b7176e0d47ec6a7a0c1034a2545b914447e8c`である。旧payload / accepted / receiptは
`/var/backups/hidloom/rpi-os-early-e2-replace-cdadc2bcd-to-0ebc76ddb-20260806T132221Z/`へchecksum付きで退避し、
新payloadは通常boot 4 fileを
`/var/backups/hidloom/rpi-os-early-e2-v2-placement-0ebc76ddb-20260806T132221Z`へbackupして
`installed-disabled`で配置した。receipt SHA-256は
`7e7844dc73a6753f8e16e5d1a1f0815aa56a45a0321064237335f1d2ed9956bd`、既定boot変更とreboot requestはfalseである。

Windows operator v4はwatcher SHA-256
`fa2b12c3b20228dcee39f02d5478ae366e4b918f07d1006ac246b77ebc532a2a`をPowerShell 5.1 parser/hash self-test後に使用した。
runtime gateはREADY 1回、baseline/final exact 3 selector ready、target event 0、
`target_operation_before_ready_zero=true`、expected exit 21 / `initial_disconnect_not_observed`をpassした。
gate report JSON / Markdown SHA-256は
`b7c4ae385fd1f0adc562552fd35e8409e40fec6472b8e01486a928df10e16b54` /
`c6f22783535d1bd6024e24ecf94961557ca7171c52343d7c068fa2a68e258212`である。

preflight boot ID `7622f176-6653-4659-9cdb-0a83f28c11b8`からtrybootを一度だけ消費し、one-shot boot ID
`7def3c57-8f1c-41d0-86b5-9f7313d22e25`へ遷移した。`hidloom.early=e1 panic=10`、early ready 3.160秒、
adopt 15.198秒、early-to-adopt 12.038秒、keyboard ready 15.770秒、UDC `configured`を確認した。
live `bMaxPacketSize0=0x40`はsnapshot v2の限定volatile entryとして検証され、adopterは
`status=adopted` / configfs mutation 0でpassした。Windows one-shotはbaseline 3891.525 ms、READY 5078.8246 ms、
initial disconnect 92017.616 ms、first re-add ready 103670.608 ms、final 127580.647 ms、
post-first-ready disconnect 0、exit 0。report JSON / Markdown SHA-256は
`f3b1b78c91136a7b50538c8b160f50ec21a1e0803091b3863cb2169eb68f4388` /
`6f88e8f99aa4995facb9f78de325ab22e1e41d74fe549d036a457a5673ac53ab`である。

ephemeral evidence回収後にfresh watcherで通常rebootを一度実行し、fallback boot ID
`749a1fad-577a-4bd5-8c7e-d1be8ecfbd04`へ戻した。early token/treeなし、keyboard ready 14.092秒、
failed unit 0、全主要service active、UDC `configured`、pressed/error 0、通常boot 4 hash不変、output `auto`をpassした。
Windows fallbackはbaseline 3902.199 ms、READY 5132.6223 ms、initial disconnect 64281.884 ms、
first re-add ready 85384.080 ms、final 127544.522 ms、post-first-ready disconnect 0、exit 0。report JSON / Markdown
SHA-256は`d20b3a303d65bb2ffdc6208a4eb899d9d1caae129e51ae12ca9d6dced9c0c797` /
`fc1de2908922caadb61bc6e83a828d8833a07492f1b3a39a4401d1432d678bf0`である。

`MemAvailable`はpackage前173 MiB、package後174 MiB、one-shot 167 MiB、fallback 171 MiB、最終fallback 174 MiB、
zram usedは4.3 MiB / 30 MiB / 276 KiB / 0 / 1.4 MiBで、one-shot/fallbackにOOMはない。最終packageは
`0.0.2043+git0ebc76ddb`、hidd write/drop/invalid 0、outputd forward/invalid 0、pressed state 0、output `auto`。
E2 corrected candidateはPASSとし、次phaseはE3 native early inputとする。証跡は
`build/artifacts/<keyboard-host>-rpi-os-early-e2-v2-0ebc76ddb-20260806T131123Z/`。
