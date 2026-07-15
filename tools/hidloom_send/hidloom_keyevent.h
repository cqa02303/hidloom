#ifndef HIDLOOM_KEYEVENT_H
#define HIDLOOM_KEYEVENT_H

#include <stdbool.h>
#include <stdint.h>

#define HIDLOOM_KEY_SOCKET_DEFAULT "/tmp/key_events.sock"
#define HIDLOOM_KEY_PRESS 0x50
#define HIDLOOM_KEY_RELEASE 0x52
#define HIDLOOM_DEFAULT_HOLD_US 30000
#define HIDLOOM_DEFAULT_GAP_US 20000

int hidloom_sleep_us(unsigned int usec);
int hidloom_write_key_event(int fd, uint8_t keycode, uint8_t modifier, bool press);
int hidloom_tap_key(int fd, uint8_t keycode, uint8_t modifier, unsigned int hold_us, unsigned int gap_us);

#endif
