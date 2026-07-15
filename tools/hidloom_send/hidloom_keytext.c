#define _POSIX_C_SOURCE 200809L

#include "hidloom_ipc.h"
#include "hidloom_keyevent.h"

#include <ctype.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MOD_LSHIFT 0x02

struct key_pair {
    uint8_t keycode;
    uint8_t modifier;
};

static void usage(FILE *out) {
    fprintf(out,
            "usage: hidloom-keytext [--socket PATH] [--hold-us N] [--gap-us N] TEXT [TEXT...]\n"
            "\n"
            "Supported escapes: \\\\n, \\\\r, \\\\t, \\\\\\\\, \\\", \\\\xNN.\n"
            "\n"
            "Options:\n"
            "  --help        show this help and exit\n");
}

static bool map_ascii(unsigned char ch, struct key_pair *out) {
    if (ch >= 'a' && ch <= 'z') {
        out->keycode = (uint8_t)(0x04 + (ch - 'a'));
        out->modifier = 0;
        return true;
    }
    if (ch >= 'A' && ch <= 'Z') {
        out->keycode = (uint8_t)(0x04 + (ch - 'A'));
        out->modifier = MOD_LSHIFT;
        return true;
    }
    if (ch >= '1' && ch <= '9') {
        out->keycode = (uint8_t)(0x1e + (ch - '1'));
        out->modifier = 0;
        return true;
    }
    if (ch == '0') {
        out->keycode = 0x27;
        out->modifier = 0;
        return true;
    }

    switch (ch) {
    case '\n':
    case '\r':
        out->keycode = 0x28;
        out->modifier = 0;
        return true;
    case '\t':
        out->keycode = 0x2b;
        out->modifier = 0;
        return true;
    case ' ':
        out->keycode = 0x2c;
        out->modifier = 0;
        return true;
    case '-':
        out->keycode = 0x2d;
        out->modifier = 0;
        return true;
    case '=':
        out->keycode = 0x2e;
        out->modifier = 0;
        return true;
    case '[':
        out->keycode = 0x2f;
        out->modifier = 0;
        return true;
    case ']':
        out->keycode = 0x30;
        out->modifier = 0;
        return true;
    case '\\':
        out->keycode = 0x31;
        out->modifier = 0;
        return true;
    case ';':
        out->keycode = 0x33;
        out->modifier = 0;
        return true;
    case '\'':
        out->keycode = 0x34;
        out->modifier = 0;
        return true;
    case '`':
        out->keycode = 0x35;
        out->modifier = 0;
        return true;
    case ',':
        out->keycode = 0x36;
        out->modifier = 0;
        return true;
    case '.':
        out->keycode = 0x37;
        out->modifier = 0;
        return true;
    case '/':
        out->keycode = 0x38;
        out->modifier = 0;
        return true;
    case '!':
        out->keycode = 0x1e;
        out->modifier = MOD_LSHIFT;
        return true;
    case '@':
        out->keycode = 0x1f;
        out->modifier = MOD_LSHIFT;
        return true;
    case '#':
        out->keycode = 0x20;
        out->modifier = MOD_LSHIFT;
        return true;
    case '$':
        out->keycode = 0x21;
        out->modifier = MOD_LSHIFT;
        return true;
    case '%':
        out->keycode = 0x22;
        out->modifier = MOD_LSHIFT;
        return true;
    case '^':
        out->keycode = 0x23;
        out->modifier = MOD_LSHIFT;
        return true;
    case '&':
        out->keycode = 0x24;
        out->modifier = MOD_LSHIFT;
        return true;
    case '*':
        out->keycode = 0x25;
        out->modifier = MOD_LSHIFT;
        return true;
    case '(':
        out->keycode = 0x26;
        out->modifier = MOD_LSHIFT;
        return true;
    case ')':
        out->keycode = 0x27;
        out->modifier = MOD_LSHIFT;
        return true;
    case '_':
        out->keycode = 0x2d;
        out->modifier = MOD_LSHIFT;
        return true;
    case '+':
        out->keycode = 0x2e;
        out->modifier = MOD_LSHIFT;
        return true;
    case '{':
        out->keycode = 0x2f;
        out->modifier = MOD_LSHIFT;
        return true;
    case '}':
        out->keycode = 0x30;
        out->modifier = MOD_LSHIFT;
        return true;
    case '|':
        out->keycode = 0x31;
        out->modifier = MOD_LSHIFT;
        return true;
    case ':':
        out->keycode = 0x33;
        out->modifier = MOD_LSHIFT;
        return true;
    case '"':
        out->keycode = 0x34;
        out->modifier = MOD_LSHIFT;
        return true;
    case '~':
        out->keycode = 0x35;
        out->modifier = MOD_LSHIFT;
        return true;
    case '<':
        out->keycode = 0x36;
        out->modifier = MOD_LSHIFT;
        return true;
    case '>':
        out->keycode = 0x37;
        out->modifier = MOD_LSHIFT;
        return true;
    case '?':
        out->keycode = 0x38;
        out->modifier = MOD_LSHIFT;
        return true;
    default:
        return false;
    }
}

static int hex_value(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

static int next_decoded(const char *text, size_t *pos, unsigned char *out) {
    unsigned char ch = (unsigned char)text[*pos];

    if (ch == '\0') {
        return 0;
    }
    (*pos)++;
    if (ch != '\\') {
        *out = ch;
        return 1;
    }

    ch = (unsigned char)text[*pos];
    if (ch == '\0') {
        *out = '\\';
        return 1;
    }
    (*pos)++;
    switch (ch) {
    case 'n':
        *out = '\n';
        return 1;
    case 'r':
        *out = '\r';
        return 1;
    case 't':
        *out = '\t';
        return 1;
    case '\\':
        *out = '\\';
        return 1;
    case '"':
        *out = '"';
        return 1;
    case 'x': {
        int hi = hex_value(text[*pos]);
        int lo = hi >= 0 ? hex_value(text[*pos + 1]) : -1;
        if (hi < 0 || lo < 0) {
            return -1;
        }
        *out = (unsigned char)((hi << 4) | lo);
        *pos += 2;
        return 1;
    }
    default:
        *out = ch;
        return 1;
    }
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

static int validate_text_args(int first_arg, int argc, char **argv) {
    int arg;
    struct key_pair pair;

    for (arg = first_arg; arg < argc; arg++) {
        size_t pos = 0;
        unsigned char ch;
        int decoded;

        if (arg > first_arg && !map_ascii(' ', &pair)) {
            return -1;
        }
        while ((decoded = next_decoded(argv[arg], &pos, &ch)) != 0) {
            if (decoded < 0) {
                fprintf(stderr, "invalid escape sequence\n");
                return -1;
            }
            if (!map_ascii(ch, &pair)) {
                fprintf(stderr, "unsupported character: 0x%02x\n", ch);
                return -1;
            }
        }
    }
    return 0;
}

static int send_text_arg(int fd, const char *text, unsigned int hold_us, unsigned int gap_us) {
    size_t pos = 0;
    unsigned char ch;
    int decoded;

    while ((decoded = next_decoded(text, &pos, &ch)) != 0) {
        struct key_pair pair;

        if (decoded < 0 || !map_ascii(ch, &pair)) {
            errno = EINVAL;
            return -1;
        }
        if (hidloom_tap_key(fd, pair.keycode, pair.modifier, hold_us, gap_us) < 0) {
            return -1;
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    const char *socket_path = HIDLOOM_KEY_SOCKET_DEFAULT;
    unsigned int hold_us = HIDLOOM_DEFAULT_HOLD_US;
    unsigned int gap_us = HIDLOOM_DEFAULT_GAP_US;
    int i = 1;
    int first_text_arg;
    int fd;

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

    if (i >= argc) {
        usage(stderr);
        return 2;
    }
    if (validate_text_args(i, argc, argv) < 0) {
        return 2;
    }
    first_text_arg = i;

    fd = hidloom_connect_unix(socket_path);
    if (fd < 0) {
        fprintf(stderr, "connect %s: %s\n", socket_path, strerror(errno));
        return 1;
    }

    for (; i < argc; i++) {
        if (i > first_text_arg) {
            struct key_pair space_pair;
            map_ascii(' ', &space_pair);
            if (hidloom_tap_key(fd, space_pair.keycode, space_pair.modifier, hold_us, gap_us) < 0) {
                fprintf(stderr, "send: %s\n", strerror(errno));
                close(fd);
                return 1;
            }
        }
        if (send_text_arg(fd, argv[i], hold_us, gap_us) < 0) {
            fprintf(stderr, "send: %s\n", strerror(errno));
            close(fd);
            return 1;
        }
    }

    close(fd);
    return 0;
}
