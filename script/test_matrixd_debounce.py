#!/usr/bin/env python3
"""Unit tests for the side-effect-free matrixd debounce helper."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEST_C = r'''
#include <stdio.h>
#include <stdlib.h>
#include "debounce.h"

static void expect_event(const char *label, MatrixdDebounceEvent got, MatrixdDebounceEvent want)
{
    if (got != want) {
        fprintf(stderr, "%s: got %d want %d\n", label, got, want);
        exit(1);
    }
}

static void expect_state(const char *label, MatrixdDebounceKey *key, unsigned want)
{
    if (key->state != want) {
        fprintf(stderr, "%s: state got %u want %u\n", label, key->state, want);
        exit(1);
    }
}

static void test_count_mode(void)
{
    MatrixdDebounceKey key;
    MatrixdDebounceEvent event;
    matrixd_debounce_init(&key);

    expect_event("count first high", matrixd_debounce_step_count(&key, 1, 3), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("count second high", matrixd_debounce_step_count(&key, 1, 3), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_count(&key, 1, 3);
    expect_event("count third high", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
    expect_state("count candidate not committed", &key, 0);
    matrixd_debounce_commit_event(&key, event);
    expect_state("count committed press", &key, 1);
    expect_event("count held high", matrixd_debounce_step_count(&key, 1, 3), MATRIXD_DEBOUNCE_EVENT_NONE);

    expect_event("count first low", matrixd_debounce_step_count(&key, 0, 3), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("count second low", matrixd_debounce_step_count(&key, 0, 3), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_count(&key, 0, 3);
    expect_event("count third low", event, MATRIXD_DEBOUNCE_EVENT_RELEASE);
    expect_state("count release candidate not committed", &key, 1);
    matrixd_debounce_commit_event(&key, event);
    expect_state("count committed release", &key, 0);
}

static void test_time_mode_ignores_high_frequency_count(void)
{
    MatrixdDebounceKey key;
    MatrixdDebounceEvent event;
    matrixd_debounce_init(&key);

    expect_event("time high t0", matrixd_debounce_step_time(&key, 1, 0, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("time high t100", matrixd_debounce_step_time(&key, 1, 100, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("time high t200", matrixd_debounce_step_time(&key, 1, 200, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("time high t300", matrixd_debounce_step_time(&key, 1, 300, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("time high t400", matrixd_debounce_step_time(&key, 1, 400, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("time high t4999", matrixd_debounce_step_time(&key, 1, 4999, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time(&key, 1, 5000, 5000);
    expect_event("time high t5000", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
    expect_state("time candidate not committed", &key, 0);
    matrixd_debounce_commit_event(&key, event);
    expect_state("time committed press", &key, 1);
}

static void test_time_mode_variable_periods(void)
{
    MatrixdDebounceKey key;
    MatrixdDebounceEvent event;
    matrixd_debounce_init(&key);

    expect_event("var high t0", matrixd_debounce_step_time(&key, 1, 0, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("var high t200", matrixd_debounce_step_time(&key, 1, 200, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("var high t1700", matrixd_debounce_step_time(&key, 1, 1700, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time(&key, 1, 5100, 5000);
    expect_event("var high t5100", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
    matrixd_debounce_commit_event(&key, event);

    expect_event("var low t5200", matrixd_debounce_step_time(&key, 0, 5200, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("var low t6000", matrixd_debounce_step_time(&key, 0, 6000, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("var low t10199", matrixd_debounce_step_time(&key, 0, 10199, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time(&key, 0, 10200, 5000);
    expect_event("var low t10200", event, MATRIXD_DEBOUNCE_EVENT_RELEASE);
    expect_state("var release candidate not committed", &key, 1);
    matrixd_debounce_commit_event(&key, event);
    expect_state("var committed release", &key, 0);
}

static void test_short_noise_is_ignored(void)
{
    MatrixdDebounceKey key;
    matrixd_debounce_init(&key);

    expect_event("noise high t0", matrixd_debounce_step_time(&key, 1, 0, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("noise high t1000", matrixd_debounce_step_time(&key, 1, 1000, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("noise low t1200", matrixd_debounce_step_time(&key, 0, 1200, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("noise low t6200", matrixd_debounce_step_time(&key, 0, 6200, 5000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_state("noise ignored", &key, 0);
}

static void test_six_ms_policy_filters_release_chatter(void)
{
    MatrixdDebounceKey key;
    MatrixdDebounceEvent event;
    matrixd_debounce_init(&key);

    event = matrixd_debounce_step_time(&key, 1, 0, 6000);
    expect_event("six ms press start", event, MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time(&key, 1, 6000, 6000);
    expect_event("six ms press commit", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
    matrixd_debounce_commit_event(&key, event);

    expect_event("release chatter start", matrixd_debounce_step_time(&key, 0, 7000, 6000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("release chatter below policy", matrixd_debounce_step_time(&key, 0, 12500, 6000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("contact restored", matrixd_debounce_step_time(&key, 1, 12600, 6000), MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_state("release chatter suppressed", &key, 1);

    expect_event("stable release start", matrixd_debounce_step_time(&key, 0, 13000, 6000), MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time(&key, 0, 19000, 6000);
    expect_event("stable release commit", event, MATRIXD_DEBOUNCE_EVENT_RELEASE);
    matrixd_debounce_commit_event(&key, event);
    expect_state("stable release accepted", &key, 0);
}

static void test_asymmetric_time_policy_and_repress_guard(void)
{
    MatrixdDebounceKey key;
    MatrixdDebounceEvent event;
    matrixd_debounce_init(&key);

    expect_event("segmented press first high",
        matrixd_debounce_step_time_policy(&key, 1, 0, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("segmented press high below threshold",
        matrixd_debounce_step_time_policy(&key, 1, 4422, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("segmented press low",
        matrixd_debounce_step_time_policy(&key, 0, 4500, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("segmented press second high",
        matrixd_debounce_step_time_policy(&key, 1, 6000, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time_policy(&key, 1, 11000, 5000, 6000, 16000);
    expect_event("segmented idle press accepted at five ms", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
    matrixd_debounce_commit_event_at(&key, event, 11000);

    expect_event("release start",
        matrixd_debounce_step_time_policy(&key, 0, 12000, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("release still below six ms",
        matrixd_debounce_step_time_policy(&key, 0, 17999, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time_policy(&key, 0, 18000, 5000, 6000, 16000);
    expect_event("release accepted at six ms", event, MATRIXD_DEBOUNCE_EVENT_RELEASE);
    matrixd_debounce_commit_event_at(&key, event, 18000);

    expect_event("guarded rebound press start",
        matrixd_debounce_step_time_policy(&key, 1, 19000, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("five point five ms rebound rejected",
        matrixd_debounce_step_time_policy(&key, 1, 24500, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_event("rebound returns low",
        matrixd_debounce_step_time_policy(&key, 0, 24600, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    expect_state("guarded rebound suppressed", &key, 0);

    expect_event("later press outside guard starts",
        matrixd_debounce_step_time_policy(&key, 1, 35000, 5000, 6000, 16000),
        MATRIXD_DEBOUNCE_EVENT_NONE);
    event = matrixd_debounce_step_time_policy(&key, 1, 40000, 5000, 6000, 16000);
    expect_event("later press accepted at five ms", event, MATRIXD_DEBOUNCE_EVENT_PRESS);
}

int main(void)
{
    test_count_mode();
    test_time_mode_ignores_high_frequency_count();
    test_time_mode_variable_periods();
    test_short_noise_is_ignored();
    test_six_ms_policy_filters_release_chatter();
    test_asymmetric_time_policy_and_repress_guard();
    puts("ok: matrixd debounce helper");
    return 0;
}
'''


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_c = tmp_path / "test_matrixd_debounce.c"
        test_bin = tmp_path / "test_matrixd_debounce"
        test_c.write_text(TEST_C, encoding="utf-8")
        subprocess.run(
            [
                "gcc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-I",
                str(ROOT / "daemon" / "matrixd"),
                str(test_c),
                str(ROOT / "daemon" / "matrixd" / "debounce.c"),
                "-o",
                str(test_bin),
            ],
            check=True,
        )
        proc = subprocess.run([str(test_bin)], check=True, text=True, stdout=subprocess.PIPE)
        assert "ok: matrixd debounce helper" in proc.stdout


if __name__ == "__main__":
    main()
