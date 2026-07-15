#!/usr/bin/env python3
"""Measure ADS1115 analog stick limits and update i2cd calibration."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from i2cd.ads1115 import ADS1115Reader, normalize_stick, parse_analog_stick_config, read_stick_volts  # noqa: E402


@dataclass(frozen=True)
class AxisStats:
    low: float
    center: float
    high: float


@dataclass(frozen=True)
class StickStats:
    x: AxisStats
    y: AxisStats
    samples: int


@dataclass(frozen=True)
class PhaseCalibration:
    x: dict[str, float]
    y: dict[str, float]
    samples: int
    phase: str


def _load_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"config not found: {path}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"config root must be an object: {path}")
    return data


def _round_volts(value: float) -> float:
    return round(float(value), 4)


def _sample(reader: ADS1115Reader, stick_cfg: Any, duration: float, interval: float) -> list[tuple[float, float]]:
    end_at = time.monotonic() + duration
    samples: list[tuple[float, float]] = []
    while True:
        samples.append(read_stick_volts(reader, stick_cfg))
        if time.monotonic() >= end_at:
            break
        time.sleep(interval)
    return samples


def _axis_stats(center_values: list[float], sweep_values: list[float], margin: float) -> AxisStats:
    center = statistics.median(center_values)
    low = min(sweep_values) - margin
    high = max(sweep_values) + margin
    if not low < center < high:
        raise SystemExit(
            f"invalid calibration range: low={low:.4f} center={center:.4f} high={high:.4f}; "
            "center the stick first, then move it through the full physical range"
        )
    return AxisStats(low=_round_volts(low), center=_round_volts(center), high=_round_volts(high))


def build_calibration(
    center_samples: list[tuple[float, float]],
    sweep_samples: list[tuple[float, float]],
    *,
    margin: float,
) -> StickStats:
    x_center = [sample[0] for sample in center_samples]
    y_center = [sample[1] for sample in center_samples]
    x_sweep = [sample[0] for sample in sweep_samples]
    y_sweep = [sample[1] for sample in sweep_samples]
    return StickStats(
        x=_axis_stats(x_center, x_sweep, margin),
        y=_axis_stats(y_center, y_sweep, margin),
        samples=len(center_samples) + len(sweep_samples),
    )


def build_center_calibration(center_samples: list[tuple[float, float]]) -> PhaseCalibration:
    return PhaseCalibration(
        x={"center": _round_volts(statistics.median(sample[0] for sample in center_samples))},
        y={"center": _round_volts(statistics.median(sample[1] for sample in center_samples))},
        samples=len(center_samples),
        phase="center",
    )


def build_range_calibration(
    sweep_samples: list[tuple[float, float]],
    *,
    margin: float,
    min_range_volts: float = 0.1,
) -> PhaseCalibration:
    x_values = [sample[0] for sample in sweep_samples]
    y_values = [sample[1] for sample in sweep_samples]
    x_span = max(x_values) - min(x_values)
    y_span = max(y_values) - min(y_values)
    if x_span < min_range_volts or y_span < min_range_volts:
        raise SystemExit(
            f"range sampling span too small: x={x_span:.4f}V y={y_span:.4f}V; "
            "move the stick through the full physical range while sampling"
        )
    return PhaseCalibration(
        x={"low": _round_volts(min(x_values) - margin), "high": _round_volts(max(x_values) + margin)},
        y={"low": _round_volts(min(y_values) - margin), "high": _round_volts(max(y_values) + margin)},
        samples=len(sweep_samples),
        phase="range",
    )


def apply_calibration(cfg: dict[str, Any], stats: StickStats) -> dict[str, Any]:
    raw = cfg.get("analog_stick")
    if not isinstance(raw, dict):
        raise SystemExit("analog_stick config is missing")
    for name, axis in (("x", stats.x), ("y", stats.y)):
        item = raw.get(name)
        if not isinstance(item, dict):
            raise SystemExit(f"analog_stick.{name} config is missing")
        item["center"] = axis.center
        item["low"] = axis.low
        item["high"] = axis.high
    return cfg


def apply_phase_calibration(cfg: dict[str, Any], stats: PhaseCalibration) -> dict[str, Any]:
    raw = cfg.get("analog_stick")
    if not isinstance(raw, dict):
        raise SystemExit("analog_stick config is missing")
    for name, values in (("x", stats.x), ("y", stats.y)):
        item = raw.get(name)
        if not isinstance(item, dict):
            raise SystemExit(f"analog_stick.{name} config is missing")
        for key, value in values.items():
            item[key] = value
    return cfg


def phase_payload(stats: PhaseCalibration) -> dict[str, Any]:
    return {
        "phase": stats.phase,
        "samples": stats.samples,
        "x": stats.x,
        "y": stats.y,
    }


def validate_saved_calibration(cfg: dict[str, Any], *, min_range_volts: float = 0.1) -> dict[str, Any]:
    if min_range_volts < 0:
        raise SystemExit("min_range_volts must be >= 0")
    try:
        stick_cfg = parse_analog_stick_config(cfg)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"invalid analog_stick config: {exc}") from exc
    if stick_cfg is None:
        raise SystemExit("analog_stick.enabled is false or analog_stick config is missing")

    errors: list[str] = []

    def axis_payload(name: str, axis: Any) -> dict[str, Any]:
        span = axis.high - axis.low
        center_valid = axis.low < axis.center < axis.high
        span_valid = span >= min_range_volts
        if not center_valid:
            errors.append(f"{name}.center must be between low and high")
        if not span_valid:
            errors.append(f"{name}.span {span:.4f}V is smaller than {min_range_volts:.4f}V")
        return {
            "channel": axis.channel,
            "center": axis.center,
            "low": axis.low,
            "high": axis.high,
            "span": round(span, 4),
            "center_valid": center_valid,
            "span_valid": span_valid,
            "invert": axis.invert,
        }

    payload = {
        "result": "ok",
        "min_range_volts": min_range_volts,
        "x": axis_payload("x", stick_cfg.x_axis),
        "y": axis_payload("y", stick_cfg.y_axis),
        "errors": errors,
    }
    payload["valid"] = not errors
    return payload


def _print_stats(stats: StickStats) -> None:
    print(
        json.dumps(
            {
                "samples": stats.samples,
                "x": {"center": stats.x.center, "low": stats.x.low, "high": stats.x.high},
                "y": {"center": stats.y.center, "low": stats.y.low, "high": stats.y.high},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_config(path: Path, cfg: dict[str, Any], *, backup: bool) -> None:
    if backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)
        print(f"backup: {backup_path}")
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated: {path}")


def _i2cd_active(service: str) -> bool:
    proc = subprocess.run(
        ["systemctl", "is-active", "--quiet", service],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def _systemctl(action: str, service: str, timeout: float) -> None:
    try:
        proc = subprocess.run(
            ["systemctl", action, service],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"systemctl {action} {service} timed out") from exc
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"systemctl {action} {service} failed: {msg or proc.returncode}")


def run_phase_calibration(
    *,
    config_path: Path,
    phase: str,
    duration: float,
    interval: float,
    margin: float,
    write: bool,
    backup: bool,
    manage_i2cd_service: bool = False,
    i2cd_service: str = "i2cd",
    service_timeout: float = 15.0,
    min_range_volts: float = 0.1,
) -> dict[str, Any]:
    if phase not in {"center", "range"}:
        raise SystemExit(f"phase must be center or range, got {phase!r}")
    if duration <= 0 or interval <= 0:
        raise SystemExit("duration and interval must be positive")
    if margin < 0:
        raise SystemExit("margin must be >= 0")
    if min_range_volts < 0:
        raise SystemExit("min_range_volts must be >= 0")

    service_was_active = False
    try:
        if manage_i2cd_service:
            service_was_active = _i2cd_active(i2cd_service)
            if service_was_active:
                _systemctl("stop", i2cd_service, service_timeout)

        cfg = _load_config(config_path)
        try:
            stick_cfg = parse_analog_stick_config(cfg)
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid analog_stick config: {exc}") from exc
        if stick_cfg is None:
            raise SystemExit("analog_stick.enabled is false or analog_stick config is missing")

        try:
            reader = ADS1115Reader(bus=stick_cfg.bus, address=stick_cfg.address)
        except Exception as exc:
            raise SystemExit(f"ADS1115 init failed: {exc}") from exc
        try:
            try:
                samples = _sample(reader, stick_cfg, duration, interval)
            except Exception as exc:
                raise SystemExit(f"ADS1115 sampling failed: {exc}") from exc
        finally:
            reader.close()
    finally:
        if manage_i2cd_service and service_was_active:
            _systemctl("start", i2cd_service, service_timeout)

    stats = (
        build_center_calibration(samples)
        if phase == "center"
        else build_range_calibration(samples, margin=margin, min_range_volts=min_range_volts)
    )
    payload = phase_payload(stats)
    if write:
        _write_config(config_path, apply_phase_calibration(cfg, stats), backup=backup)
        payload["written"] = True
        payload["config"] = str(config_path)
    else:
        payload["written"] = False
    return payload


def watch_stick(
    *,
    config_path: Path,
    duration: float,
    interval: float,
    manage_i2cd_service: bool,
    i2cd_service: str = "i2cd",
    service_timeout: float = 15.0,
) -> None:
    if duration <= 0 or interval <= 0:
        raise SystemExit("duration and interval must be positive")

    service_was_active = False
    try:
        if manage_i2cd_service:
            service_was_active = _i2cd_active(i2cd_service)
            if service_was_active:
                _systemctl("stop", i2cd_service, service_timeout)

        cfg = _load_config(config_path)
        try:
            stick_cfg = parse_analog_stick_config(cfg)
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid analog_stick config: {exc}") from exc
        if stick_cfg is None:
            raise SystemExit("analog_stick.enabled is false or analog_stick config is missing")

        try:
            reader = ADS1115Reader(bus=stick_cfg.bus, address=stick_cfg.address)
        except Exception as exc:
            raise SystemExit(f"ADS1115 init failed: {exc}") from exc
        try:
            end_at = time.monotonic() + duration
            x_low = y_low = float("inf")
            x_high = y_high = float("-inf")
            while True:
                try:
                    x_volts, y_volts = read_stick_volts(reader, stick_cfg)
                except Exception as exc:
                    raise SystemExit(f"ADS1115 sampling failed: {exc}") from exc
                x_low = min(x_low, x_volts)
                x_high = max(x_high, x_volts)
                y_low = min(y_low, y_volts)
                y_high = max(y_high, y_volts)
                x_norm, y_norm = normalize_stick(x_volts, y_volts, stick_cfg)
                print(
                    f"x={x_volts:.4f}V y={y_volts:.4f}V norm=({x_norm:4d},{y_norm:4d}) "
                    f"span=({x_high - x_low:.4f}V,{y_high - y_low:.4f}V)",
                    flush=True,
                )
                if time.monotonic() >= end_at:
                    break
                time.sleep(interval)
        finally:
            reader.close()
    finally:
        if manage_i2cd_service and service_was_active:
            _systemctl("start", i2cd_service, service_timeout)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure board-specific ADS1115 analog stick center/min/max and update config/default/i2cd.json",
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "default" / "i2cd.json")
    parser.add_argument("--center-duration", type=float, default=2.0)
    parser.add_argument("--sweep-duration", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=0.02)
    parser.add_argument(
        "--margin-volts",
        type=float,
        default=0.0,
        help="optional margin added beyond measured low/high; default records measured possible range",
    )
    parser.add_argument(
        "--phase",
        choices=("interactive", "center", "range", "watch", "validate"),
        default="interactive",
        help=(
            "interactive records center and range; center/range run one non-interactive phase; "
            "watch prints live values; validate checks saved calibration without hardware access"
        ),
    )
    parser.add_argument("--write", action="store_true", help="update the config file; otherwise only print values")
    parser.add_argument("--no-backup", action="store_true", help="do not create CONFIG.bak when writing")
    parser.add_argument(
        "--min-range-volts",
        type=float,
        default=0.1,
        help="reject range calibration unless both axes move at least this much",
    )
    parser.add_argument(
        "--manage-i2cd-service",
        action="store_true",
        help="temporarily stop i2cd while sampling, then restart it if it was active",
    )
    args = parser.parse_args()

    if args.center_duration <= 0 or args.sweep_duration <= 0 or args.interval <= 0:
        raise SystemExit("durations and interval must be positive")
    if args.margin_volts < 0:
        raise SystemExit("--margin-volts must be >= 0")
    if args.phase != "validate" and args.manage_i2cd_service and os.geteuid() != 0:
        raise SystemExit("--manage-i2cd-service requires root; run with sudo")

    if args.phase == "validate":
        payload = validate_saved_calibration(_load_config(args.config), min_range_volts=args.min_range_volts)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload["valid"]:
            raise SystemExit(1)
        return

    if args.phase == "watch":
        watch_stick(
            config_path=args.config,
            duration=args.sweep_duration,
            interval=args.interval,
            manage_i2cd_service=args.manage_i2cd_service,
        )
        return

    if args.phase in {"center", "range"}:
        duration = args.center_duration if args.phase == "center" else args.sweep_duration
        payload = run_phase_calibration(
            config_path=args.config,
            phase=args.phase,
            duration=duration,
            interval=args.interval,
            margin=args.margin_volts,
            write=args.write,
            backup=not args.no_backup,
            manage_i2cd_service=args.manage_i2cd_service,
            min_range_volts=args.min_range_volts,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not args.write:
            print("dry-run: pass --write to save these values")
        return

    service_was_active = False
    try:
        if args.manage_i2cd_service:
            service_was_active = _i2cd_active("i2cd")
            if service_was_active:
                _systemctl("stop", "i2cd", 15.0)

        cfg = _load_config(args.config)
        try:
            stick_cfg = parse_analog_stick_config(cfg)
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid analog_stick config: {exc}") from exc
        if stick_cfg is None:
            raise SystemExit("analog_stick.enabled is false or analog_stick config is missing")

        try:
            reader = ADS1115Reader(bus=stick_cfg.bus, address=stick_cfg.address)
        except Exception as exc:
            raise SystemExit(f"ADS1115 init failed: {exc}") from exc
        try:
            input(f"Release the stick to center, then press Enter. Sampling {args.center_duration:.1f}s...")
            try:
                center_samples = _sample(reader, stick_cfg, args.center_duration, args.interval)
            except Exception as exc:
                raise SystemExit(f"ADS1115 center sampling failed: {exc}") from exc
            input(
                "Move the stick through its full physical range in circles, then press Enter. "
                f"Sampling {args.sweep_duration:.1f}s..."
            )
            try:
                sweep_samples = _sample(reader, stick_cfg, args.sweep_duration, args.interval)
            except Exception as exc:
                raise SystemExit(f"ADS1115 range sampling failed: {exc}") from exc
        finally:
            reader.close()
    finally:
        if args.manage_i2cd_service and service_was_active:
            _systemctl("start", "i2cd", 15.0)

    stats = build_calibration(center_samples, sweep_samples, margin=args.margin_volts)
    _print_stats(stats)
    updated = apply_calibration(cfg, stats)
    if args.write:
        _write_config(args.config, updated, backup=not args.no_backup)
    else:
        print("dry-run: pass --write to save these values")


if __name__ == "__main__":
    main()
