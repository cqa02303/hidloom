#define _POSIX_C_SOURCE 200809L

#include "hidloom_ipc.h"
#include "hidloom_keyevent.h"

#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void usage(FILE *out) {
    fprintf(out,
            "usage: hidloom-key [--socket PATH] [--hold-us N] [--gap-us N] tap KEYCHORD [KEYCHORD...]\n"
            "       hidloom-key [--socket PATH] press|release KEYCHORD|KEY [MOD]\n"
            "\n"
            "KEYCHORD is 0xMMKK where MM is modifier and KK is HID keycode.\n"
            "KEY without modifier may be written as 0xKK.\n"
            "KEY and MOD are numeric, decimal or 0x-prefixed, range 0..255.\n"
            "\n"
            "Options:\n"
            "  --help        show this help and exit\n");
}

static int parse_u8(const char *text, uint8_t *out) {
    char *end = NULL;
    unsigned long value;

    errno = 0;
    value = strtoul(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value > 255UL) {
        return -1;
    }
    *out = (uint8_t)value;
    return 0;
}

static int parse_u16(const char *text, uint16_t *out) {
    char *end = NULL;
    unsigned long value;

    errno = 0;
    value = strtoul(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value > 65535UL) {
        return -1;
    }
    *out = (uint16_t)value;
    return 0;
}

static int parse_keychord(const char *text, uint8_t *keycode, uint8_t *modifier) {
    uint16_t chord;

    if (parse_u16(text, &chord) < 0) {
        return -1;
    }
    *keycode = (uint8_t)(chord & 0xff);
    *modifier = (uint8_t)((chord >> 8) & 0xff);
    return 0;
}

static int parse_us(const char *text, unsigned int *out) {
    char *end = NULL;
    unsigned long value;

    errno = 0;
    value = strtoul(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value > 3600000000UL) {
        return -1;
    }
    *out = (unsigned int)value;
    return 0;
}

int main(int argc, char **argv) {
    const char *socket_path = HIDLOOM_KEY_SOCKET_DEFAULT;
    unsigned int hold_us = HIDLOOM_DEFAULT_HOLD_US;
    unsigned int gap_us = HIDLOOM_DEFAULT_GAP_US;
    const char *op;
    int fd;
    int i = 1;
    int rc;

    while (i < argc && strncmp(argv[i], "--", 2) == 0) {
        if (strcmp(argv[i], "--help") == 0) {
            usage(stdout);
            return 0;
        } else if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[i + 1];
            i += 2;
        } else if (strcmp(argv[i], "--hold-us") == 0 && i + 1 < argc) {
            if (parse_us(argv[i + 1], &hold_us) < 0) {
                fprintf(stderr, "invalid --hold-us: %s\n", argv[i + 1]);
                return 2;
            }
            i += 2;
        } else if (strcmp(argv[i], "--gap-us") == 0 && i + 1 < argc) {
            if (parse_us(argv[i + 1], &gap_us) < 0) {
                fprintf(stderr, "invalid --gap-us: %s\n", argv[i + 1]);
                return 2;
            }
            i += 2;
        } else {
            usage(stderr);
            return 2;
        }
    }

    if (argc - i < 2) {
        usage(stderr);
        return 2;
    }

    op = argv[i++];

    fd = hidloom_connect_unix(socket_path);
    if (fd < 0) {
        fprintf(stderr, "connect %s: %s\n", socket_path, strerror(errno));
        return 1;
    }

    if (strcmp(op, "tap") == 0) {
        rc = 0;
        while (i < argc) {
            uint8_t keycode;
            uint8_t modifier;
            if (parse_keychord(argv[i++], &keycode, &modifier) < 0) {
                fprintf(stderr, "invalid keychord\n");
                close(fd);
                return 2;
            }
            rc = hidloom_tap_key(fd, keycode, modifier, hold_us, gap_us);
            if (rc < 0) {
                break;
            }
        }
    } else if (strcmp(op, "press") == 0) {
        uint8_t keycode;
        uint8_t modifier = 0;
        int remaining = argc - i;
        if (remaining == 1) {
            if (parse_keychord(argv[i++], &keycode, &modifier) < 0) {
                fprintf(stderr, "invalid keychord\n");
                close(fd);
                return 2;
            }
        } else if (remaining == 2) {
            if (parse_u8(argv[i++], &keycode) < 0 || parse_u8(argv[i++], &modifier) < 0) {
                fprintf(stderr, "invalid keycode or modifier\n");
                close(fd);
                return 2;
            }
        } else {
            fprintf(stderr, "invalid keycode\n");
            close(fd);
            return 2;
        }
        rc = hidloom_write_key_event(fd, keycode, modifier, true);
    } else if (strcmp(op, "release") == 0) {
        uint8_t keycode;
        uint8_t modifier = 0;
        int remaining = argc - i;
        if (remaining == 1) {
            if (parse_keychord(argv[i++], &keycode, &modifier) < 0) {
                fprintf(stderr, "invalid keychord\n");
                close(fd);
                return 2;
            }
        } else if (remaining == 2) {
            if (parse_u8(argv[i++], &keycode) < 0 || parse_u8(argv[i++], &modifier) < 0) {
                fprintf(stderr, "invalid keycode or modifier\n");
                close(fd);
                return 2;
            }
        } else {
            fprintf(stderr, "invalid keycode\n");
            close(fd);
            return 2;
        }
        rc = hidloom_write_key_event(fd, keycode, modifier, false);
    } else {
        close(fd);
        usage(stderr);
        return 2;
    }

    if (rc < 0) {
        fprintf(stderr, "send: %s\n", strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    return 0;
}
