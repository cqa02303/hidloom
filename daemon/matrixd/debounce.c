#include "debounce.h"

#include <stddef.h>

void matrixd_debounce_init(MatrixdDebounceKey *key)
{
    if (key == NULL)
        return;
    key->raw = 0;
    key->state = 0;
    key->count = 0;
    key->raw_since_us = 0;
    key->last_release_us = 0;
}

MatrixdDebounceEvent matrixd_debounce_step_count(
    MatrixdDebounceKey *key,
    uint8_t new_raw,
    uint8_t threshold
)
{
    if (key == NULL)
        return MATRIXD_DEBOUNCE_EVENT_NONE;
    if (threshold < 1)
        threshold = 1;

    if (new_raw == key->raw) {
        if (key->count < 255)
            key->count++;
    } else {
        key->raw = new_raw;
        key->count = 1;
    }

    if (key->count >= threshold && new_raw != key->state)
        return new_raw ? MATRIXD_DEBOUNCE_EVENT_PRESS : MATRIXD_DEBOUNCE_EVENT_RELEASE;
    return MATRIXD_DEBOUNCE_EVENT_NONE;
}

MatrixdDebounceEvent matrixd_debounce_step_time(
    MatrixdDebounceKey *key,
    uint8_t new_raw,
    int64_t now_us,
    int64_t debounce_us
)
{
    return matrixd_debounce_step_time_policy(
        key,
        new_raw,
        now_us,
        debounce_us,
        debounce_us,
        0
    );
}

MatrixdDebounceEvent matrixd_debounce_step_time_policy(
    MatrixdDebounceKey *key,
    uint8_t new_raw,
    int64_t now_us,
    int64_t press_debounce_us,
    int64_t release_debounce_us,
    int64_t repress_guard_us
)
{
    int64_t debounce_us;

    if (key == NULL)
        return MATRIXD_DEBOUNCE_EVENT_NONE;
    if (press_debounce_us < 0)
        press_debounce_us = 0;
    if (release_debounce_us < 0)
        release_debounce_us = 0;
    if (repress_guard_us < 0)
        repress_guard_us = 0;

    if (new_raw != key->raw) {
        key->raw = new_raw;
        key->raw_since_us = now_us;
        key->count = 1;
        return MATRIXD_DEBOUNCE_EVENT_NONE;
    }

    if (key->count < 255)
        key->count++;

    debounce_us = new_raw ? press_debounce_us : release_debounce_us;
    if (new_raw
        && key->last_release_us > 0
        && key->raw_since_us >= key->last_release_us
        && (key->raw_since_us - key->last_release_us) <= repress_guard_us
        && release_debounce_us > debounce_us) {
        debounce_us = release_debounce_us;
    }

    if ((now_us - key->raw_since_us) >= debounce_us && new_raw != key->state)
        return new_raw ? MATRIXD_DEBOUNCE_EVENT_PRESS : MATRIXD_DEBOUNCE_EVENT_RELEASE;
    return MATRIXD_DEBOUNCE_EVENT_NONE;
}

void matrixd_debounce_commit_event(
    MatrixdDebounceKey *key,
    MatrixdDebounceEvent event
)
{
    matrixd_debounce_commit_event_at(key, event, 0);
}

void matrixd_debounce_commit_event_at(
    MatrixdDebounceKey *key,
    MatrixdDebounceEvent event,
    int64_t now_us
)
{
    if (key == NULL)
        return;
    if (event == MATRIXD_DEBOUNCE_EVENT_PRESS)
        key->state = 1;
    else if (event == MATRIXD_DEBOUNCE_EVENT_RELEASE) {
        key->state = 0;
        if (now_us > 0)
            key->last_release_us = now_us;
    }
}
