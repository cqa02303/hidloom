#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUILDROOT=${BUILDROOT_DIR:-$ROOT/build/artifacts/buildroot-upstream}
OUTPUT=${BUILDROOT_OUTPUT:-$ROOT/build/artifacts/buildroot-m6-output}
EXTERNAL=$ROOT/build/buildroot/hidloom-external
NATIVE=${HIDLOOM_M6_NATIVE_DIR:-$ROOT/build/artifacts/buildroot-m4-native/bin}
HOSTBIN=${HIDLOOM_BUILD_HOSTBIN:-$ROOT/build/artifacts/buildroot-hostbin}
MODE=${1:-all}

case "$MODE" in
    --configure-only|--source|--legal-info|all)
        ;;
    *)
        echo "usage: $0 [--configure-only|--source|--legal-info]" >&2
        exit 2
        ;;
esac

python3 "$ROOT/tools/buildroot_source_prepare.py" --destination "$BUILDROOT"

mkdir -p "$HOSTBIN"
if command -v gnuinstall >/dev/null 2>&1; then
    ln -sf "$(command -v gnuinstall)" "$HOSTBIN/install"
fi

PATH="$HOSTBIN:$PATH" make -C "$BUILDROOT" O="$OUTPUT" BR2_EXTERNAL="$EXTERNAL" hidloom_m6_defconfig

repair_python_target_cache() {
    python_root=$OUTPUT/target/usr/lib/python3.14
    [ -d "$python_root" ] || return 0

    for required in \
        encodings/aliases.pyc \
        site-packages/PIL/Image.pyc \
        site-packages/cbor2/__init__.pyc \
        site-packages/luma/core/__init__.pyc \
        site-packages/luma/oled/__init__.pyc \
        site-packages/rpi_ws281x/rpi_ws281x.pyc \
        site-packages/smbus2/smbus2.pyc; do
        if [ ! -f "$python_root/$required" ]; then
            echo "repairing incomplete M6 PYC_ONLY target cache" >&2
            PATH="$HOSTBIN:$PATH" make -C "$BUILDROOT" O="$OUTPUT" BR2_EXTERNAL="$EXTERNAL" \
                python3-reinstall \
                python-cbor2-reinstall \
                python-pillow-reinstall \
                python-rpi-ws281x-reinstall \
                python-smbus2-reinstall \
                python-luma-core-reinstall \
                python-luma-oled-reinstall
            return 0
        fi
    done
}

case "$MODE" in
    --configure-only)
        exit 0
        ;;
    --source)
        PATH="$HOSTBIN:$PATH" make -C "$BUILDROOT" O="$OUTPUT" source
        ;;
    --legal-info)
        PATH="$HOSTBIN:$PATH" make -C "$BUILDROOT" O="$OUTPUT" source
        PATH="$HOSTBIN:$PATH" python3 "$ROOT/tools/buildroot_legal_info.py" --output "$OUTPUT" --execute
        ;;
    all)
        "$ROOT/tools/buildroot_m4_native_build.sh" "$(dirname "$NATIVE")"
        repair_python_target_cache
        HIDLOOM_M6_NATIVE_DIR="$NATIVE" PATH="$HOSTBIN:$PATH" make -C "$BUILDROOT" O="$OUTPUT"
        python3 "$ROOT/tools/buildroot_m6_verify.py" --output "$OUTPUT"
        python3 "$ROOT/tools/buildroot_m6_import_smoke.py" --output "$OUTPUT"
        python3 "$ROOT/tools/buildroot_m6_runtime_smoke.py" --output "$OUTPUT"
        ;;
esac
