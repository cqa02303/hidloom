#define _POSIX_C_SOURCE 200809L

#include "hidloom_ipc.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define HIDLOOM_CTRL_SOCKET_DEFAULT "/tmp/ctrl_events.sock"

static void usage(FILE *out) {
    fprintf(out,
            "usage: hidloom-ctrl [--socket PATH] json JSON\n"
            "       hidloom-ctrl [--socket PATH] keymap|matrix|save\n"
            "       hidloom-ctrl [--socket PATH] layer get|add|clear [N]\n"
            "       hidloom-ctrl [--socket PATH] output auto|usb|bt|pi\n"
            "       hidloom-ctrl [--socket PATH] bt status|power-on|power-off|power-toggle|pairing-on|pairing-off|pairing-toggle|disconnect|forget\n"
            "       hidloom-ctrl [--socket PATH] led get|save|effect MODE SPEED H S V\n"
            "\n"
            "Sends one JSON-line request to logicd control socket and prints the response.\n"
            "\n"
            "Options:\n"
            "  --help        show this help and exit\n");
}

static int parse_int(const char *text, int *out) {
    char *end = NULL;
    long value;

    errno = 0;
    value = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value < 0 || value > 31) {
        return -1;
    }
    *out = (int)value;
    return 0;
}

static int parse_byte(const char *text, int *out) {
    char *end = NULL;
    long value;

    errno = 0;
    value = strtol(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value < 0 || value > 255) {
        return -1;
    }
    *out = (int)value;
    return 0;
}

static const char *bt_action_for_shortcut(const char *op) {
    if (strcmp(op, "status") == 0) return "BT_STATUS";
    if (strcmp(op, "power-on") == 0) return "BT_POWER_ON";
    if (strcmp(op, "power-off") == 0) return "BT_POWER_OFF";
    if (strcmp(op, "power-toggle") == 0) return "BT_POWER_TOGGLE";
    if (strcmp(op, "pairing-on") == 0) return "BT_PAIRING_ON";
    if (strcmp(op, "pairing-off") == 0) return "BT_PAIRING_OFF";
    if (strcmp(op, "pairing-toggle") == 0) return "BT_PAIRING_TOGGLE";
    if (strcmp(op, "disconnect") == 0) return "BT_DISCONNECT";
    if (strcmp(op, "forget") == 0) return "BT_FORGET_DEVICE";
    return NULL;
}

static const char *output_target_for_shortcut(const char *target) {
    if (strcmp(target, "auto") == 0) return "auto";
    if (strcmp(target, "usb") == 0) return "gadget";
    if (strcmp(target, "gadget") == 0) return "gadget";
    if (strcmp(target, "bt") == 0) return "bt";
    if (strcmp(target, "bluetooth") == 0) return "bt";
    if (strcmp(target, "pi") == 0) return "uinput";
    if (strcmp(target, "uinput") == 0) return "uinput";
    return NULL;
}

static int send_request(int fd, const char *json) {
    size_t len = strlen(json);

    if (hidloom_send_all(fd, json, len) < 0) {
        return -1;
    }
    return hidloom_send_all(fd, "\n", 1);
}

static int print_response(int fd) {
    char buf[256];
    int saw_data = 0;

    for (;;) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (n == 0) {
            break;
        }
        saw_data = 1;
        if (fwrite(buf, 1, (size_t)n, stdout) != (size_t)n) {
            errno = EIO;
            return -1;
        }
        if (memchr(buf, '\n', (size_t)n) != NULL) {
            break;
        }
    }
    if (!saw_data) {
        errno = EPIPE;
        return -1;
    }
    return fflush(stdout);
}

static int build_request(int argc, char **argv, int i, char *out, size_t out_len) {
    const char *cmd;

    if (argc - i < 1) {
        return -1;
    }
    cmd = argv[i++];
    if (strcmp(cmd, "json") == 0) {
        if (argc - i != 1) {
            return -1;
        }
        if (strlen(argv[i]) + 1 > out_len) {
            errno = ENAMETOOLONG;
            return -1;
        }
        strcpy(out, argv[i]);
        return 0;
    }
    if (strcmp(cmd, "keymap") == 0) {
        return snprintf(out, out_len, "{\"t\":\"G\"}") >= (int)out_len ? -1 : 0;
    }
    if (strcmp(cmd, "matrix") == 0) {
        return snprintf(out, out_len, "{\"t\":\"K\"}") >= (int)out_len ? -1 : 0;
    }
    if (strcmp(cmd, "save") == 0) {
        return snprintf(out, out_len, "{\"t\":\"S\"}") >= (int)out_len ? -1 : 0;
    }
    if (strcmp(cmd, "layer") == 0) {
        const char *op;
        int layer;

        if (argc - i < 1) {
            return -1;
        }
        op = argv[i++];
        if (strcmp(op, "get") == 0) {
            if (argc - i != 0) {
                return -1;
            }
            return snprintf(out, out_len, "{\"t\":\"G\"}") >= (int)out_len ? -1 : 0;
        }
        if (strcmp(op, "add") == 0) {
            if (argc - i != 0) {
                return -1;
            }
            return snprintf(out, out_len, "{\"t\":\"LAYER_ADD\"}") >= (int)out_len ? -1 : 0;
        }
        if (strcmp(op, "clear") == 0) {
            if (argc - i != 1 || parse_int(argv[i], &layer) < 0) {
                return -1;
            }
            return snprintf(out, out_len, "{\"t\":\"LAYER_CLEAR\",\"l\":%d}", layer) >= (int)out_len ? -1 : 0;
        }
    }
    if (strcmp(cmd, "output") == 0) {
        const char *target;

        if (argc - i != 1) {
            return -1;
        }
        target = output_target_for_shortcut(argv[i]);
        if (target == NULL) {
            return -1;
        }
        return snprintf(out, out_len, "{\"t\":\"OUTPUT\",\"target\":\"%s\"}", target) >= (int)out_len ? -1 : 0;
    }
    if (strcmp(cmd, "bt") == 0) {
        const char *action;

        if (argc - i != 1) {
            return -1;
        }
        action = bt_action_for_shortcut(argv[i]);
        if (action == NULL) {
            return -1;
        }
        return snprintf(out, out_len, "{\"t\":\"BT\",\"action\":\"%s\"}", action) >= (int)out_len ? -1 : 0;
    }
    if (strcmp(cmd, "led") == 0) {
        const char *op;
        int mode;
        int speed;
        int h;
        int s;
        int v;

        if (argc - i < 1) {
            return -1;
        }
        op = argv[i++];
        if (strcmp(op, "get") == 0) {
            if (argc - i != 0) {
                return -1;
            }
            return snprintf(out, out_len, "{\"t\":\"LED\",\"op\":\"vialrgb_get\"}") >= (int)out_len ? -1 : 0;
        }
        if (strcmp(op, "save") == 0) {
            if (argc - i != 0) {
                return -1;
            }
            return snprintf(out, out_len, "{\"t\":\"LED\",\"op\":\"vialrgb_save\"}") >= (int)out_len ? -1 : 0;
        }
        if (strcmp(op, "effect") == 0) {
            if (argc - i != 5 ||
                parse_byte(argv[i], &mode) < 0 ||
                parse_byte(argv[i + 1], &speed) < 0 ||
                parse_byte(argv[i + 2], &h) < 0 ||
                parse_byte(argv[i + 3], &s) < 0 ||
                parse_byte(argv[i + 4], &v) < 0) {
                return -1;
            }
            return snprintf(
                out,
                out_len,
                "{\"t\":\"LED\",\"op\":\"vialrgb\",\"mode\":%d,\"speed\":%d,\"h\":%d,\"s\":%d,\"v\":%d}",
                mode,
                speed,
                h,
                s,
                v
            ) >= (int)out_len ? -1 : 0;
        }
    }
    return -1;
}

int main(int argc, char **argv) {
    const char *socket_path = HIDLOOM_CTRL_SOCKET_DEFAULT;
    char request[1024];
    int i = 1;
    int fd;

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

    if (build_request(argc, argv, i, request, sizeof(request)) < 0) {
        usage(stderr);
        return 2;
    }

    fd = hidloom_connect_unix(socket_path);
    if (fd < 0) {
        fprintf(stderr, "connect %s: %s\n", socket_path, strerror(errno));
        return 1;
    }
    if (send_request(fd, request) < 0) {
        fprintf(stderr, "send: %s\n", strerror(errno));
        close(fd);
        return 1;
    }
    if (print_response(fd) < 0) {
        fprintf(stderr, "read: %s\n", strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    return 0;
}
