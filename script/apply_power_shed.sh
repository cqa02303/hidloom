#!/usr/bin/env bash
set -euo pipefail

target_max="${HIDLOOM_POWER_CPU_MAX_KHZ:-1000000}"
target_min="${HIDLOOM_POWER_CPU_MIN_KHZ:-600000}"
target_governor="${HIDLOOM_POWER_CPU_GOVERNOR:-ondemand}"

choose_freq() {
    local policy_dir="$1"
    local target="$2"
    local available
    if [[ -r "$policy_dir/scaling_available_frequencies" ]]; then
        available="$(tr ' ' '\n' <"$policy_dir/scaling_available_frequencies" | awk -v target="$target" '$1 <= target { print $1 }' | sort -n | tail -n 1)"
        if [[ -n "$available" ]]; then
            printf '%s\n' "$available"
            return
        fi
    fi
    printf '%s\n' "$target"
}

wait_for_cpufreq() {
    local _attempt
    for _attempt in {1..40}; do
        compgen -G "/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq" >/dev/null && return 0
        sleep 0.25
    done
    return 1
}

if ! wait_for_cpufreq; then
    echo "cpufreq sysfs not available; skipping power shed" >&2
    exit 0
fi

for policy_dir in /sys/devices/system/cpu/cpu*/cpufreq; do
    [[ -d "$policy_dir" ]] || continue
    max_freq="$(choose_freq "$policy_dir" "$target_max")"
    min_freq="$(choose_freq "$policy_dir" "$target_min")"
    if [[ -w "$policy_dir/scaling_governor" ]]; then
        printf '%s\n' "$target_governor" >"$policy_dir/scaling_governor" 2>/dev/null || true
    fi
    if [[ -w "$policy_dir/scaling_min_freq" ]]; then
        printf '%s\n' "$min_freq" >"$policy_dir/scaling_min_freq" 2>/dev/null || true
    fi
    if [[ -w "$policy_dir/scaling_max_freq" ]]; then
        printf '%s\n' "$max_freq" >"$policy_dir/scaling_max_freq" 2>/dev/null || true
    fi
    echo "$(basename "$(dirname "$policy_dir")"): governor=$target_governor min=${min_freq} max=${max_freq}"
done
