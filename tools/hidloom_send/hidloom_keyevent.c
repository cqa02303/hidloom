#define _POSIX_C_SOURCE 200809L

#include "hidloom_keyevent.h"
#include "hidloom_ipc.h"

#include <errno.h>
#include <time.h>

int hidloom_sleep_us(unsigned int usec) {
    struct timespec req;

    req.tv_sec = (time_t)(usec / 1000000U);
    req.tv_nsec = (long)(usec % 1000000U) * 1000L;
    while (nanosleep(&req, &req) < 0) {
        if (errno != EINTR) {
            return -1;
        }
    }
    return 0;
}

int hidloom_write_key_event(int fd, uint8_t keycode, uint8_t modifier, bool press) {
    unsigned char pkt[4];

    pkt[0] = press ? HIDLOOM_KEY_PRESS : HIDLOOM_KEY_RELEASE;
    pkt[1] = keycode;
    pkt[2] = modifier;
    pkt[3] = 0x00;
    return hidloom_send_all(fd, pkt, sizeof(pkt));
}

int hidloom_tap_key(int fd, uint8_t keycode, uint8_t modifier, unsigned int hold_us, unsigned int gap_us) {
    if (hidloom_write_key_event(fd, keycode, modifier, true) < 0) {
        return -1;
    }
    if (hidloom_sleep_us(hold_us) < 0) {
        return -1;
    }
    if (hidloom_write_key_event(fd, keycode, modifier, false) < 0) {
        return -1;
    }
    if (gap_us > 0 && hidloom_sleep_us(gap_us) < 0) {
        return -1;
    }
    return 0;
}
