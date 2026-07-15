#ifndef MATRIXD_DEBOUNCE_H
#define MATRIXD_DEBOUNCE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    MATRIXD_DEBOUNCE_EVENT_NONE = 0,
    MATRIXD_DEBOUNCE_EVENT_PRESS = 1,
    MATRIXD_DEBOUNCE_EVENT_RELEASE = 2,
} MatrixdDebounceEvent;

typedef struct {
    uint8_t raw;
    uint8_t state;
    uint8_t count;
    int64_t raw_since_us;
} MatrixdDebounceKey;

void matrixd_debounce_init(MatrixdDebounceKey *key);

/*
 * Step functions update raw tracking and return a candidate event, but do not
 * commit key->state. Call matrixd_debounce_commit_event() only after the event
 * packet was successfully delivered to logicd.
 */
MatrixdDebounceEvent matrixd_debounce_step_count(
    MatrixdDebounceKey *key,
    uint8_t new_raw,
    uint8_t threshold
);

MatrixdDebounceEvent matrixd_debounce_step_time(
    MatrixdDebounceKey *key,
    uint8_t new_raw,
    int64_t now_us,
    int64_t debounce_us
);

void matrixd_debounce_commit_event(
    MatrixdDebounceKey *key,
    MatrixdDebounceEvent event
);

#ifdef __cplusplus
}
#endif

#endif /* MATRIXD_DEBOUNCE_H */
