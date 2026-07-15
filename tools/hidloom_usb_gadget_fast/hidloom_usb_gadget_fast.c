#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define GADGET_NAME "cqa02303v5"
#define DEFAULT_GADGET_ROOT "/sys/kernel/config/usb_gadget"
#define DEFAULT_VENDOR_ID "0x1d6b"
#define DEFAULT_PRODUCT_ID "0x0105"
#define DEFAULT_SERIAL "vial:f64c2b3c"

static const uint8_t HID_USB0_REPORT_DESC[] = {
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xE0,
    0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x95, 0x01, 0x75, 0x08, 0x81, 0x03, 0x95, 0x06, 0x75, 0x08, 0x15, 0x00,
    0x26, 0xFF, 0x00, 0x05, 0x07, 0x19, 0x00, 0x2A, 0xFF, 0x00, 0x81, 0x00,
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01,
    0x95, 0x05, 0x91, 0x02, 0x75, 0x03, 0x95, 0x01, 0x91, 0x03, 0xC0, 0x05,
    0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x02, 0x09, 0x01, 0xA1, 0x00, 0x05,
    0x09, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95,
    0x05, 0x81, 0x02, 0x75, 0x03, 0x95, 0x01, 0x81, 0x03, 0x05, 0x01, 0x09,
    0x30, 0x09, 0x31, 0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95,
    0x03, 0x81, 0x06, 0xC0, 0xC0, 0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85,
    0x03, 0x15, 0x00, 0x26, 0xFF, 0x03, 0x19, 0x00, 0x2A, 0xFF, 0x03, 0x75,
    0x10, 0x95, 0x01, 0x81, 0x00, 0xC0,
};

static const uint8_t HID_USB1_REPORT_DESC[] = {
    0x06, 0x60, 0xFF, 0x09, 0x61, 0xA1, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
    0x75, 0x08, 0x95, 0x20, 0x09, 0x62, 0x81, 0x02, 0x95, 0x20, 0x09, 0x63,
    0x91, 0x02, 0xC0,
};

static const uint8_t HID_USB2_REPORT_DESC[] = {
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01,
    0x75, 0x08, 0x81, 0x03, 0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x26, 0xFF,
    0x00, 0x05, 0x07, 0x19, 0x00, 0x2A, 0xFF, 0x00, 0x81, 0x00, 0x05, 0x08,
    0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x05,
    0x91, 0x02, 0x75, 0x03, 0x95, 0x01, 0x91, 0x03, 0xC0,
};

static const uint8_t HID_USB4_REPORT_DESC[] = {
    0x06, 0x70, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x15, 0x00, 0x26, 0xFF, 0x00,
    0x75, 0x08, 0x95, 0x08, 0x09, 0x02, 0x81, 0x02, 0x95, 0x08, 0x09, 0x03,
    0x91, 0x02, 0xC0,
};

typedef struct {
    const char *root;
    char hostname[128];
    char vendor_id[16];
    char product_id[16];
    char manufacturer[128];
    char product_name[128];
    char serial[128];
    int us_sub_keyboard;
    int windows_ime_custom_hid;
} Config;

static int env_bool(const char *name, int default_value) {
    const char *raw = getenv(name);
    if (!raw || !*raw) return default_value;
    char buf[32];
    size_t i = 0;
    for (; raw[i] && i < sizeof(buf) - 1; i++) {
        buf[i] = (char)tolower((unsigned char)raw[i]);
    }
    buf[i] = '\0';
    if (strcmp(buf, "1") == 0 || strcmp(buf, "true") == 0 || strcmp(buf, "yes") == 0 ||
        strcmp(buf, "on") == 0 || strcmp(buf, "enabled") == 0) {
        return 1;
    }
    if (strcmp(buf, "0") == 0 || strcmp(buf, "false") == 0 || strcmp(buf, "no") == 0 ||
        strcmp(buf, "off") == 0 || strcmp(buf, "disabled") == 0) {
        return 0;
    }
    fprintf(stderr, "invalid boolean %s=%s\n", name, raw);
    exit(2);
}

static void copy_env(char *dst, size_t dst_size, const char *name, const char *fallback) {
    const char *raw = getenv(name);
    snprintf(dst, dst_size, "%s", (raw && *raw) ? raw : fallback);
}

static void resolve_hostname_placeholder(char *value, size_t value_size, const char *hostname) {
    if (strcmp(value, "__HOSTNAME__") == 0) {
        snprintf(value, value_size, "%s", hostname);
    }
}

static void checked_snprintf(char *dst, size_t dst_size, const char *fmt,
                             const char *a, const char *b) {
    int n = snprintf(dst, dst_size, fmt, a, b);
    if (n < 0 || (size_t)n >= dst_size) {
        fprintf(stderr, "path too long\n");
        exit(1);
    }
}

static void path_join(char *dst, size_t dst_size, const char *a, const char *b) {
    checked_snprintf(dst, dst_size, "%s/%s", a, b);
}

static int exists_path(const char *path) {
    struct stat st;
    return stat(path, &st) == 0;
}

static void mkdir_p(const char *path) {
    char tmp[PATH_MAX];
    snprintf(tmp, sizeof(tmp), "%s", path);
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0755) < 0 && errno != EEXIST) {
                perror(tmp);
                exit(1);
            }
            *p = '/';
        }
    }
    if (mkdir(tmp, 0755) < 0 && errno != EEXIST) {
        perror(tmp);
        exit(1);
    }
}

static void write_file(const char *path, const void *data, size_t len) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        perror(path);
        exit(1);
    }
    const uint8_t *p = (const uint8_t *)data;
    while (len > 0) {
        ssize_t n = write(fd, p, len);
        if (n < 0) {
            perror(path);
            close(fd);
            exit(1);
        }
        p += n;
        len -= (size_t)n;
    }
    close(fd);
}

static void write_text(const char *path, const char *text) {
    write_file(path, text, strlen(text));
}

static void write_child_text(const char *base, const char *child, const char *text) {
    char path[PATH_MAX];
    path_join(path, sizeof(path), base, child);
    write_text(path, text);
}

static void write_child_bytes(const char *base, const char *child, const uint8_t *data, size_t len) {
    char path[PATH_MAX];
    path_join(path, sizeof(path), base, child);
    write_file(path, data, len);
}

static void unlink_if_exists(const char *path) {
    if (unlink(path) < 0 && errno != ENOENT) {
        perror(path);
        exit(1);
    }
}

static void rmdir_if_exists(const char *path) {
    if (rmdir(path) < 0 && errno != ENOENT && errno != ENOTEMPTY && errno != EPERM) {
        perror(path);
        exit(1);
    }
}

static void unbind_if_needed(const char *gadget) {
    char path[PATH_MAX];
    path_join(path, sizeof(path), gadget, "UDC");
    if (exists_path(path)) {
        write_text(path, "");
    }
}

static void remove_existing(const char *gadget) {
    if (!exists_path(gadget)) return;
    unbind_if_needed(gadget);

    const char *fns[] = {"hid.usb0", "hid.usb1", "hid.usb2", "hid.usb3", "hid.usb4"};
    for (size_t i = 0; i < sizeof(fns) / sizeof(fns[0]); i++) {
        char path[PATH_MAX];
        checked_snprintf(path, sizeof(path), "%s/configs/c.1/%s", gadget, fns[i]);
        unlink_if_exists(path);
    }

    const char *dirs[] = {
        "configs/c.1/strings/0x411",
        "configs/c.1/strings/0x409",
        "configs/c.1",
        "configs",
        "functions/hid.usb4",
        "functions/hid.usb3",
        "functions/hid.usb2",
        "functions/hid.usb1",
        "functions/hid.usb0",
        "functions",
        "strings/0x411",
        "strings/0x409",
        "strings",
        "",
    };
    for (size_t i = 0; i < sizeof(dirs) / sizeof(dirs[0]); i++) {
        char path[PATH_MAX];
        if (dirs[i][0]) {
            path_join(path, sizeof(path), gadget, dirs[i]);
        } else {
            snprintf(path, sizeof(path), "%s", gadget);
        }
        rmdir_if_exists(path);
    }
}

static void write_hid_function(const char *gadget, const char *fn, const char *protocol,
                               const char *subclass, const char *report_length,
                               const uint8_t *desc, size_t desc_len) {
    char dir[PATH_MAX];
    checked_snprintf(dir, sizeof(dir), "%s/functions/%s", gadget, fn);
    mkdir_p(dir);
    write_child_text(dir, "protocol", protocol);
    write_child_text(dir, "subclass", subclass);
    write_child_text(dir, "report_length", report_length);
    write_child_bytes(dir, "report_desc", desc, desc_len);
}

static void write_strings(const char *base, const Config *cfg) {
    char dir[PATH_MAX];
    checked_snprintf(dir, sizeof(dir), "%s/strings/0x409", base, "");
    mkdir_p(dir);
    write_child_text(dir, "serialnumber", cfg->serial);
    write_child_text(dir, "manufacturer", cfg->manufacturer);
    write_child_text(dir, "product", cfg->product_name);

    checked_snprintf(dir, sizeof(dir), "%s/strings/0x411", base, "");
    mkdir_p(dir);
    write_child_text(dir, "serialnumber", cfg->serial);
    write_child_text(dir, "manufacturer", cfg->manufacturer);
    write_child_text(dir, "product", cfg->product_name);
}

static void symlink_fn(const char *gadget, const char *fn) {
    char target[PATH_MAX];
    char link_path[PATH_MAX];
    checked_snprintf(target, sizeof(target), "%s/functions/%s", gadget, fn);
    checked_snprintf(link_path, sizeof(link_path), "%s/configs/c.1/%s", gadget, fn);
    if (symlink(target, link_path) < 0 && errno != EEXIST) {
        perror(link_path);
        exit(1);
    }
}

static void find_udc(char *out, size_t out_size) {
    DIR *dir = opendir("/sys/class/udc");
    if (!dir) {
        perror("/sys/class/udc");
        exit(1);
    }
    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL) {
        if (ent->d_name[0] == '.') continue;
        if (strlen(ent->d_name) >= out_size) {
            fprintf(stderr, "UDC name too long\n");
            exit(1);
        }
        strcpy(out, ent->d_name);
        closedir(dir);
        return;
    }
    closedir(dir);
    fprintf(stderr, "no UDC found\n");
    exit(1);
}

static int lookup_group_gid(const char *name, gid_t *out) {
    FILE *fp = fopen("/etc/group", "r");
    if (!fp) return 0;

    char line[512];
    while (fgets(line, sizeof(line), fp)) {
        char *group_name = line;
        char *password = strchr(group_name, ':');
        if (!password) continue;
        *password = '\0';
        if (strcmp(group_name, name) != 0) continue;

        char *gid_text = strchr(password + 1, ':');
        if (!gid_text) continue;
        gid_text++;

        errno = 0;
        char *end = NULL;
        unsigned long value = strtoul(gid_text, &end, 10);
        if (errno == 0 && end != gid_text) {
            *out = (gid_t)value;
            fclose(fp);
            return 1;
        }
    }

    fclose(fp);
    return 0;
}

static void configure_hidg_permissions(const char *path) {
    gid_t gid;
    if (lookup_group_gid("input", &gid)) {
        if (chown(path, (uid_t)-1, gid) < 0) {
            perror(path);
        }
    }
    (void)chmod(path, 0660);
}

static void wait_for_hidg(const Config *cfg) {
    const char *devs[4];
    size_t count = 0;
    devs[count++] = "/dev/hidg0";
    devs[count++] = "/dev/hidg1";
    if (cfg->us_sub_keyboard) devs[count++] = "/dev/hidg2";
    if (cfg->windows_ime_custom_hid) devs[count++] = "/dev/hidg4";

    struct timespec delay = {.tv_sec = 0, .tv_nsec = 50000000L};
    for (int attempt = 0; attempt < 20; attempt++) {
        int all_ready = 1;
        for (size_t i = 0; i < count; i++) {
            struct stat st;
            if (stat(devs[i], &st) < 0 || !S_ISCHR(st.st_mode)) {
                all_ready = 0;
                break;
            }
        }
        if (all_ready) break;
        nanosleep(&delay, NULL);
    }
    for (size_t i = 0; i < count; i++) {
        if (exists_path(devs[i])) {
            configure_hidg_permissions(devs[i]);
        } else {
            fprintf(stderr, "warning: expected HID device did not appear: %s\n", devs[i]);
        }
    }
}

static void load_config(Config *cfg) {
    cfg->root = getenv("HIDLOOM_USB_GADGET_ROOT");
    if (!cfg->root || !*cfg->root) cfg->root = DEFAULT_GADGET_ROOT;

    if (gethostname(cfg->hostname, sizeof(cfg->hostname)) < 0) {
        snprintf(cfg->hostname, sizeof(cfg->hostname), "cqa02303v5");
    }
    cfg->hostname[sizeof(cfg->hostname) - 1] = '\0';

    copy_env(cfg->vendor_id, sizeof(cfg->vendor_id), "HIDLOOM_USB_VENDOR_ID", DEFAULT_VENDOR_ID);
    copy_env(cfg->product_id, sizeof(cfg->product_id), "HIDLOOM_USB_PRODUCT_ID", DEFAULT_PRODUCT_ID);
    copy_env(
        cfg->manufacturer, sizeof(cfg->manufacturer), "HIDLOOM_USB_MANUFACTURER", cfg->hostname
    );
    copy_env(
        cfg->product_name, sizeof(cfg->product_name), "HIDLOOM_USB_PRODUCT_NAME", cfg->hostname
    );
    copy_env(cfg->serial, sizeof(cfg->serial), "HIDLOOM_USB_SERIAL", DEFAULT_SERIAL);
    resolve_hostname_placeholder(cfg->manufacturer, sizeof(cfg->manufacturer), cfg->hostname);
    resolve_hostname_placeholder(cfg->product_name, sizeof(cfg->product_name), cfg->hostname);
    resolve_hostname_placeholder(cfg->serial, sizeof(cfg->serial), cfg->hostname);
    const char *suffix = getenv("HIDLOOM_USB_SERIAL_SUFFIX");
    if (suffix && *suffix) {
        size_t used = strlen(cfg->serial);
        snprintf(cfg->serial + used, sizeof(cfg->serial) - used, ":%s", suffix);
    }
    cfg->us_sub_keyboard = env_bool("HIDLOOM_USB_US_SUB_KEYBOARD", 1);
    cfg->windows_ime_custom_hid = env_bool("HIDLOOM_WINDOWS_IME_CUSTOM_HID", 0);
}

int main(void) {
    Config cfg;
    memset(&cfg, 0, sizeof(cfg));
    load_config(&cfg);

    char gadget[PATH_MAX];
    path_join(gadget, sizeof(gadget), cfg.root, GADGET_NAME);

    printf("USB HID Keyboard Gadget Setup (native fast path)\n");
    printf("  Root:       %s\n", cfg.root);
    printf("  Product:    %s\n", cfg.product_name);
    printf("  US sub KBD: %d\n", cfg.us_sub_keyboard);
    printf("  Win IME:    %d\n", cfg.windows_ime_custom_hid);

    remove_existing(gadget);
    mkdir_p(gadget);
    write_child_text(gadget, "idVendor", cfg.vendor_id);
    write_child_text(gadget, "idProduct", cfg.product_id);
    write_child_text(gadget, "bcdDevice", "0x0100");
    write_child_text(gadget, "bcdUSB", "0x0200");
    write_strings(gadget, &cfg);

    write_hid_function(gadget, "hid.usb0", "0", "0", "9", HID_USB0_REPORT_DESC, sizeof(HID_USB0_REPORT_DESC));
    write_hid_function(gadget, "hid.usb1", "0", "0", "32", HID_USB1_REPORT_DESC, sizeof(HID_USB1_REPORT_DESC));
    if (cfg.us_sub_keyboard) {
        write_hid_function(gadget, "hid.usb2", "1", "1", "8", HID_USB2_REPORT_DESC, sizeof(HID_USB2_REPORT_DESC));
    }
    if (cfg.windows_ime_custom_hid) {
        write_hid_function(gadget, "hid.usb4", "0", "0", "8", HID_USB4_REPORT_DESC, sizeof(HID_USB4_REPORT_DESC));
    }

    char c1[PATH_MAX];
    checked_snprintf(c1, sizeof(c1), "%s/configs/c.1", gadget, "");
    mkdir_p(c1);
    char c1s[PATH_MAX];
    checked_snprintf(c1s, sizeof(c1s), "%s/strings/0x409", c1, "");
    mkdir_p(c1s);
    write_child_text(
        c1s,
        "configuration",
        cfg.us_sub_keyboard
            ? "Config 1: HID Keyboard+Mouse+Consumer+RawHID+UsSubKeyboard"
            : "Config 1: HID Keyboard+Mouse+Consumer+RawHID"
    );
    checked_snprintf(c1s, sizeof(c1s), "%s/strings/0x411", c1, "");
    mkdir_p(c1s);
    write_child_text(
        c1s,
        "configuration",
        cfg.us_sub_keyboard
            ? "Config 1: HID Keyboard+Mouse+Consumer+RawHID+UsSubKeyboard"
            : "Config 1: HID Keyboard+Mouse+Consumer+RawHID"
    );
    write_child_text(c1, "MaxPower", "250");

    symlink_fn(gadget, "hid.usb0");
    symlink_fn(gadget, "hid.usb1");
    if (cfg.us_sub_keyboard) symlink_fn(gadget, "hid.usb2");
    if (cfg.windows_ime_custom_hid) symlink_fn(gadget, "hid.usb4");

    char udc[128];
    find_udc(udc, sizeof(udc));
    write_child_text(gadget, "UDC", udc);
    wait_for_hidg(&cfg);

    printf("USB HID gadget configured\n");
    printf("  Product: %s\n", cfg.product_name);
    printf("  UDC:     %s\n", udc);
    return 0;
}
