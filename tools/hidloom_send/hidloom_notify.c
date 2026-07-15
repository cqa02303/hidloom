#define _POSIX_C_SOURCE 200809L

#include "hidloom_ipc.h"

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>

#define HIDLOOM_I2C_SOCKET_DEFAULT "/tmp/i2c_events.sock"

static void usage(FILE *out) {
    fprintf(out,
            "usage: hidloom-notify [--socket PATH] alert|warning MESSAGE [SEC]\n"
            "\n"
            "Logs to syslog and sends an OLED alert/warning. SEC defaults to 2.0 seconds.\n"
            "\n"
            "Options:\n"
            "  --help        show this help and exit\n");
}

static int append_char(char *buf, size_t cap, size_t *pos, char ch) {
    if (*pos + 1 >= cap) {
        errno = ENOSPC;
        return -1;
    }
    buf[*pos] = ch;
    (*pos)++;
    buf[*pos] = '\0';
    return 0;
}

static int append_text(char *buf, size_t cap, size_t *pos, const char *text) {
    while (*text != '\0') {
        if (append_char(buf, cap, pos, *text++) < 0) {
            return -1;
        }
    }
    return 0;
}

static int append_json_string(char *buf, size_t cap, size_t *pos, const char *text) {
    const unsigned char *p = (const unsigned char *)text;

    if (append_char(buf, cap, pos, '"') < 0) {
        return -1;
    }
    while (*p != '\0') {
        unsigned char ch = *p++;
        char esc[7];

        switch (ch) {
        case '"':
            if (append_text(buf, cap, pos, "\\\"") < 0) return -1;
            break;
        case '\\':
            if (append_text(buf, cap, pos, "\\\\") < 0) return -1;
            break;
        case '\n':
            if (append_text(buf, cap, pos, "\\n") < 0) return -1;
            break;
        case '\r':
            if (append_text(buf, cap, pos, "\\r") < 0) return -1;
            break;
        case '\t':
            if (append_text(buf, cap, pos, "\\t") < 0) return -1;
            break;
        default:
            if (ch < 0x20) {
                snprintf(esc, sizeof(esc), "\\u%04x", ch);
                if (append_text(buf, cap, pos, esc) < 0) return -1;
            } else if (append_char(buf, cap, pos, (char)ch) < 0) {
                return -1;
            }
            break;
        }
    }
    return append_char(buf, cap, pos, '"');
}

static int build_message(char *buf, size_t cap, const char *kind, const char *message, double sec) {
    size_t pos = 0;
    char tail[64];

    buf[0] = '\0';
    if (append_text(buf, cap, &pos, "{\"t\":") < 0) return -1;
    if (append_json_string(buf, cap, &pos, kind) < 0) return -1;
    if (append_text(buf, cap, &pos, ",\"msg\":") < 0) return -1;
    if (append_json_string(buf, cap, &pos, message) < 0) return -1;
    snprintf(tail, sizeof(tail), ",\"sec\":%.3f}\n", sec);
    return append_text(buf, cap, &pos, tail);
}

int main(int argc, char **argv) {
    const char *socket_path = HIDLOOM_I2C_SOCKET_DEFAULT;
    const char *kind;
    const char *message;
    double sec = 2.0;
    char *end = NULL;
    char json[1024];
    int fd;
    int priority;
    int i = 1;

    while (i < argc && strncmp(argv[i], "--", 2) == 0) {
        if (strcmp(argv[i], "--help") == 0) {
            usage(stdout);
            return 0;
        } else if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[i + 1];
            i += 2;
        } else {
            usage(stderr);
            return 2;
        }
    }

    if (argc - i < 2 || argc - i > 3) {
        usage(stderr);
        return 2;
    }
    kind = argv[i++];
    message = argv[i++];
    if (strcmp(kind, "alert") == 0) {
        priority = LOG_INFO;
    } else if (strcmp(kind, "warning") == 0) {
        priority = LOG_WARNING;
    } else {
        usage(stderr);
        return 2;
    }
    if (i < argc) {
        errno = 0;
        sec = strtod(argv[i], &end);
        if (errno != 0 || end == argv[i] || *end != '\0' || sec < 0.1 || sec > 60.0) {
            fprintf(stderr, "invalid SEC: %s\n", argv[i]);
            return 2;
        }
    }

    if (build_message(json, sizeof(json), kind, message, sec) < 0) {
        fprintf(stderr, "message too long\n");
        return 2;
    }

    openlog("hidloom-notify", LOG_PID, LOG_USER);
    syslog(priority, "%s: %s", kind, message);
    closelog();

    fd = hidloom_connect_unix(socket_path);
    if (fd < 0) {
        fprintf(stderr, "connect %s: %s\n", socket_path, strerror(errno));
        return 1;
    }
    if (hidloom_send_all(fd, json, strlen(json)) < 0) {
        fprintf(stderr, "send: %s\n", strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    return 0;
}
