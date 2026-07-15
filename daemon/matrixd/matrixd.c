/*
 * matrixd.c — チャーリープレックス GPIO マトリクス・スキャナ
 *
 * 概要
 * ----
 *   config/default/matrixd.json を読み込み、Raspberry Pi の /dev/gpiomem 経由で
 *   キーマトリクスをスキャンして、logicd の Unix ドメインソケットへ
 *   キーイベントを送信する。
 *
 * パケット形式 (4 バイト固定)
 * ---------------------------
 *   [ type(P/R) | row_hex_char | col_hex_char | '\n' ]
 *   例: 'P', '1', '4', '\n'  → row=1, col=4 押下
 *
 * チャーリープレックス・スキャン手順
 * ------------------------------------
 *   ROW i をスキャンする際:
 *     1. GPIO[i] を OUTPUT LOW に設定
 *     2. 他の全 GPIO は INPUT PULL-UP のまま
 *     3. GPIO[j] (j != i) を読み取り; LOW なら key(i,j) 押下
 *     4. GPIO[i] を INPUT に戻す
 */

#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <ctype.h>
#include <signal.h>
#include <syslog.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>

#include "debounce.h"

/* ------------------------------------------------------------------ */
/* 定数                                                                 */
/* ------------------------------------------------------------------ */

#define MAX_GPIOS       16
#define MAX_ROWS        16
#define MAX_COLS        16
#define MAX_DIRECT_SWITCHES 32
#define MAX_ROTARY_ENCODERS 8
#define MAX_PATH_LEN    128
#define CONFIG_BUF_SIZE 8192
#define LOGICD_CONNECT_RETRY_US 50000
#define TAP_CONNECT_RETRY_MS 1000
#define GPIO_MAP_SIZE   4096        /* /dev/gpiomem のマップサイズ (1ページ) */
#define MIN_INTERVAL_US 50          /* RT設定時でもbusy loop化させない下限 */

/* GPIO レジスタ (uint32_t 配列インデックス) */
#define REG_GPFSEL(n)  ((n))        /* n=0-5、GPFSEL0-5 */
#define REG_GPSET0     (0x1C / 4)
#define REG_GPCLR0     (0x28 / 4)
#define REG_GPLEV0     (0x34 / 4)
#define REG_GPPUD      (0x94 / 4)
#define REG_GPPUDCLK0  (0x98 / 4)

/* ------------------------------------------------------------------ */
/* 設定構造体                                                            */
/* ------------------------------------------------------------------ */

typedef struct {
    int row;
    int col;
    int gpio;
    int pullup;
    int active_low;
} DirectSwitchConfig;

typedef struct {
    int gpio_a;
    int gpio_b;
    int row_a;
    int col_a;
    int row_b;
    int col_b;
    int pullup;
    int active_low;
} RotaryEncoderConfig;

typedef struct {
    int  rows;
    int  cols;
    int  row_gpios[MAX_ROWS];
    int  col_gpios[MAX_COLS];
    int  matrix_enabled;   /* 0=matrix scan を無効化し、direct/encoder のみ使う */
    int  skip_same_index;   /* チャーリープレックス: row == col をスキップ */
    int  row_drive_low;     /* 1=output_low でスキャン、0=output_high     */
    int  col_pullup;        /* 1=pull_up、0=pull_down                     */
    int  key_active_low;    /* 1=LOW アクティブ、0=HIGH アクティブ         */
    int  direct_switch_count;
    DirectSwitchConfig direct_switches[MAX_DIRECT_SWITCHES];
    int  rotary_encoder_count;
    RotaryEncoderConfig rotary_encoders[MAX_ROTARY_ENCODERS];
    int  interval_us;       /* 1 回の全行スキャン後に待機するマイクロ秒   */
    int  idle_interval_us;  /* 無操作時の scan 待機時間 (0=無効)          */
    int  deep_idle_interval_us; /* 長めの無操作時の scan 待機時間 (0=無効) */
    int  idle_after_ms;     /* この時間無変化なら idle_interval_us へ移行 */
    int  deep_idle_after_ms;/* この時間無変化なら deep_idle_interval_us へ移行 */
    int  debounce_ms;       /* チャタリング除去時間 (ミリ秒)               */
    int  debounce_count;    /* デバウンス確定スキャン数 (0=debounce_msから自動計算) */
    int  startup_quiet_ms;  /* 起動直後は状態同期のみ行いイベントを送らない時間 */
    char debounce_mode[16]; /* count=既存scan回数方式, time=実時間方式     */
    int  gpio_enabled;      /* 0=GPIO を操作しない (ハードウェア未接続テスト用) */
    int  settle_us;         /* ROW ドライブ後のセトリング待ち時間 (µs)    */
    int  post_row_settle_us;/* ROW を INPUT に戻した後の待ち時間 (µs)     */
    int  reapply_pull_each_scan; /* 1=各 row scan 後に pull を再設定する旧挙動 */
    char socket_path[MAX_PATH_LEN];
    char tap_socket_path[MAX_PATH_LEN];
    char event_log_path[MAX_PATH_LEN];
} Config;

/* ------------------------------------------------------------------ */
/* グローバル                                                            */
/* ------------------------------------------------------------------ */

static volatile uint32_t *g_gpio = NULL;
static volatile sig_atomic_t g_running = 1;

/* ------------------------------------------------------------------ */
/* シグナルハンドラ                                                      */
/* ------------------------------------------------------------------ */

static void sig_handler(int sig) { (void)sig; g_running = 0; }

/* ================================================================== */
/* 簡易 JSON パーサ (固定フォーマット向け)                               */
/* ================================================================== */

/* JSON テキスト中のキー "key" の値先頭ポインタを返す */
static const char *json_find(const char *json, const char *key)
{
    char pat[64];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) return NULL;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ':')
        p++;
    return p;
}

static int json_int(const char *json, const char *key, int def)
{
    const char *p = json_find(json, key);
    return p ? atoi(p) : def;
}

static int json_bool(const char *json, const char *key, int def)
{
    const char *p = json_find(json, key);
    if (!p) return def;
    if (strncmp(p, "true",  4) == 0) return 1;
    if (strncmp(p, "false", 5) == 0) return 0;
    return def;
}

static const char *json_find_between(const char *start, const char *end, const char *key)
{
    char pat[64];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = start;
    while (p && p < end) {
        p = strstr(p, pat);
        if (!p || p >= end)
            return NULL;
        p += strlen(pat);
        while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ':'))
            p++;
        return p;
    }
    return NULL;
}

static int json_obj_int(const char *start, const char *end, const char *key, int def)
{
    const char *p = json_find_between(start, end, key);
    return p ? atoi(p) : def;
}

static int json_obj_bool(const char *start, const char *end, const char *key, int def)
{
    const char *p = json_find_between(start, end, key);
    if (!p) return def;
    if (strncmp(p, "true", 4) == 0) return 1;
    if (strncmp(p, "false", 5) == 0) return 0;
    return def;
}

static void json_obj_str(const char *start, const char *end, const char *key,
                         char *buf, int bufsz, const char *def)
{
    const char *p = json_find_between(start, end, key);
    if (!p || p >= end || *p != '"') {
        strncpy(buf, def, bufsz - 1);
        buf[bufsz - 1] = '\0';
        return;
    }
    p++;
    int i = 0;
    while (p < end && *p && *p != '"' && i < bufsz - 1)
        buf[i++] = *p++;
    buf[i] = '\0';
}

static int json_obj_int_pair(const char *start, const char *end, const char *key,
                             int *a, int *b)
{
    const char *p = json_find_between(start, end, key);
    if (!p || p >= end || *p != '[')
        return 0;
    p++;
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r'))
        p++;
    if (p >= end)
        return 0;
    *a = atoi(p);
    while (p < end && *p != ',' && *p != ']')
        p++;
    if (p >= end || *p != ',')
        return 0;
    p++;
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r'))
        p++;
    if (p >= end)
        return 0;
    *b = atoi(p);
    return 1;
}

static void json_str(const char *json, const char *key,
                     char *buf, int bufsz, const char *def)
{
    const char *p = json_find(json, key);
    if (!p || *p != '"') {
        strncpy(buf, def, bufsz - 1);
        buf[bufsz - 1] = '\0';
        return;
    }
    p++;
    int i = 0;
    while (*p && *p != '"' && i < bufsz - 1)
        buf[i++] = *p++;
    buf[i] = '\0';
}

/* JSON 整数配列を解析して arr に格納、個数を返す */
static int json_int_array(const char *json, const char *key,
                          int *arr, int max_len)
{
    const char *p = json_find(json, key);
    if (!p || *p != '[') return 0;
    p++;
    int n = 0;
    while (*p && *p != ']' && n < max_len) {
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ',')
            p++;
        if (*p == ']') break;
        if (isdigit((unsigned char)*p) || *p == '-') {
            arr[n++] = atoi(p);
            while (*p && *p != ',' && *p != ']') p++;
        } else {
            break;
        }
    }
    return n;
}

static const char *json_next_object(const char *p, const char *end, const char **obj_end)
{
    while (p && p < end && *p != '{' && *p != ']')
        p++;
    if (!p || p >= end || *p != '{')
        return NULL;
    const char *q = p + 1;
    while (q < end && *q != '}')
        q++;
    if (q >= end)
        return NULL;
    *obj_end = q;
    return p;
}

static const char *json_array_end(const char *p)
{
    if (!p || *p != '[')
        return NULL;
    const char *start = p;
    int depth = 0;
    int in_string = 0;
    for (; *p; p++) {
        if (*p == '"' && (p == start || p[-1] != '\\')) {
            in_string = !in_string;
            continue;
        }
        if (in_string)
            continue;
        if (*p == '[')
            depth++;
        else if (*p == ']') {
            depth--;
            if (depth == 0)
                return p;
        }
    }
    return NULL;
}

static int coord_in_range(const Config *cfg, int row, int col)
{
    return row >= 0 && row < cfg->rows && col >= 0 && col < cfg->cols;
}

static int parse_pullup_active(const char *start, const char *end, int default_pullup, int default_active_low,
                               int *pullup, int *active_low)
{
    char tmp[32];
    json_obj_str(start, end, "pull", tmp, sizeof(tmp), default_pullup ? "up" : "down");
    *pullup = (strncmp(tmp, "up", 2) == 0 || strncmp(tmp, "pull_up", 7) == 0);
    json_obj_str(start, end, "active", tmp, sizeof(tmp), default_active_low ? "low" : "high");
    *active_low = (strncmp(tmp, "low", 3) == 0);
    *pullup = json_obj_bool(start, end, "pullup", *pullup);
    *active_low = json_obj_bool(start, end, "active_low", *active_low);
    return 0;
}

static int parse_direct_switches(const char *json, Config *cfg)
{
    const char *p = json_find(json, "direct_switches");
    if (!p || *p != '[')
        return 0;
    const char *end = json_array_end(p);
    if (!end) {
        syslog(LOG_ERR, "direct_switches 配列が閉じていません");
        return -1;
    }

    cfg->direct_switch_count = 0;
    p++;
    while (cfg->direct_switch_count < MAX_DIRECT_SWITCHES) {
        const char *obj_end = NULL;
        const char *obj = json_next_object(p, end, &obj_end);
        if (!obj)
            break;
        DirectSwitchConfig *sw = &cfg->direct_switches[cfg->direct_switch_count];
        sw->row = json_obj_int(obj, obj_end, "row", -1);
        sw->col = json_obj_int(obj, obj_end, "col", -1);
        sw->gpio = json_obj_int(obj, obj_end, "gpio", -1);
        parse_pullup_active(obj, obj_end, cfg->col_pullup, cfg->key_active_low, &sw->pullup, &sw->active_low);
        if (!coord_in_range(cfg, sw->row, sw->col) || sw->gpio < 0 || sw->gpio > 31) {
            syslog(LOG_ERR, "direct_switches[%d] 不正 row=%d col=%d gpio=%d",
                   cfg->direct_switch_count, sw->row, sw->col, sw->gpio);
            return -1;
        }
        cfg->direct_switch_count++;
        p = obj_end + 1;
    }
    return 0;
}

static int parse_rotary_encoders(const char *json, Config *cfg)
{
    const char *p = json_find(json, "rotary_encoders");
    if (!p || *p != '[')
        return 0;
    const char *end = json_array_end(p);
    if (!end) {
        syslog(LOG_ERR, "rotary_encoders 配列が閉じていません");
        return -1;
    }

    cfg->rotary_encoder_count = 0;
    p++;
    while (cfg->rotary_encoder_count < MAX_ROTARY_ENCODERS) {
        const char *obj_end = NULL;
        const char *obj = json_next_object(p, end, &obj_end);
        if (!obj)
            break;
        RotaryEncoderConfig *enc = &cfg->rotary_encoders[cfg->rotary_encoder_count];
        enc->gpio_a = json_obj_int(obj, obj_end, "gpio_a", -1);
        enc->gpio_b = json_obj_int(obj, obj_end, "gpio_b", -1);
        if (!json_obj_int_pair(obj, obj_end, "a", &enc->row_a, &enc->col_a)) {
            enc->row_a = json_obj_int(obj, obj_end, "row_a", -1);
            enc->col_a = json_obj_int(obj, obj_end, "col_a", -1);
        }
        if (!json_obj_int_pair(obj, obj_end, "b", &enc->row_b, &enc->col_b)) {
            enc->row_b = json_obj_int(obj, obj_end, "row_b", -1);
            enc->col_b = json_obj_int(obj, obj_end, "col_b", -1);
        }
        parse_pullup_active(obj, obj_end, cfg->col_pullup, cfg->key_active_low, &enc->pullup, &enc->active_low);
        if (!coord_in_range(cfg, enc->row_a, enc->col_a)
            || !coord_in_range(cfg, enc->row_b, enc->col_b)
            || enc->gpio_a < 0 || enc->gpio_a > 31
            || enc->gpio_b < 0 || enc->gpio_b > 31) {
            syslog(LOG_ERR, "rotary_encoders[%d] 不正 gpio_a=%d gpio_b=%d a=(%d,%d) b=(%d,%d)",
                   cfg->rotary_encoder_count, enc->gpio_a, enc->gpio_b,
                   enc->row_a, enc->col_a, enc->row_b, enc->col_b);
            return -1;
        }
        cfg->rotary_encoder_count++;
        p = obj_end + 1;
    }
    return 0;
}

static void clamp_min_int(int *value, int min_value, const char *name)
{
    if (*value < min_value) {
        syslog(LOG_WARNING, "%s=%d は小さすぎるため %d に丸めます", name, *value, min_value);
        *value = min_value;
    }
}

static void clamp_nonnegative_int(int *value, const char *name)
{
    if (*value < 0) {
        syslog(LOG_WARNING, "%s=%d は負値のため 0 に丸めます", name, *value);
        *value = 0;
    }
}

/* ================================================================== */
/* 設定読み込み                                                          */
/* ================================================================== */

static int config_load(const char *path, Config *cfg)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        syslog(LOG_ERR, "設定ファイルを開けません: %s: %s", path, strerror(errno));
        return -1;
    }
    char buf[CONFIG_BUF_SIZE];
    size_t len = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[len] = '\0';

    cfg->rows           = json_int (buf, "rows",             10);
    cfg->cols           = json_int (buf, "cols",             10);
    char matrix_type[32];
    json_str(buf, "matrix_type", matrix_type, sizeof(matrix_type), "charlieplex");
    if (strncmp(matrix_type, "row_col", 7) == 0 || strncmp(matrix_type, "matrix", 6) == 0) {
        cfg->matrix_enabled = 1;
        cfg->skip_same_index = json_bool(buf, "skip_same_index", 0);
    } else if (strncmp(matrix_type, "none", 4) == 0 || strncmp(matrix_type, "disabled", 8) == 0) {
        cfg->matrix_enabled = 0;
        cfg->skip_same_index = json_bool(buf, "skip_same_index", 0);
    } else {
        cfg->matrix_enabled = 1;
        cfg->skip_same_index = json_bool(buf, "skip_same_index", 1);
    }
    cfg->interval_us    = json_int (buf, "interval_us",      500);
    cfg->idle_interval_us = json_int(buf, "idle_interval_us", 0);
    cfg->deep_idle_interval_us = json_int(buf, "deep_idle_interval_us", 0);
    cfg->idle_after_ms = json_int(buf, "idle_after_ms", 0);
    cfg->deep_idle_after_ms = json_int(buf, "deep_idle_after_ms", 0);
    cfg->debounce_ms    = json_int (buf, "debounce_ms",        5);
    cfg->debounce_count = json_int (buf, "debounce_count",     0);
    cfg->startup_quiet_ms = json_int(buf, "startup_quiet_ms",  0);
    json_str(buf, "debounce_mode", cfg->debounce_mode, sizeof(cfg->debounce_mode), "count");
    cfg->gpio_enabled   = json_bool(buf, "gpio_enabled",       1);
    cfg->settle_us      = json_int (buf, "settle_us",         20);
    cfg->post_row_settle_us = json_int(buf, "post_row_settle_us", 2);
    cfg->reapply_pull_each_scan = json_bool(buf, "reapply_pull_each_scan", 0);

    clamp_min_int(&cfg->interval_us, MIN_INTERVAL_US, "interval_us");
    clamp_nonnegative_int(&cfg->idle_interval_us, "idle_interval_us");
    clamp_nonnegative_int(&cfg->deep_idle_interval_us, "deep_idle_interval_us");
    clamp_nonnegative_int(&cfg->idle_after_ms, "idle_after_ms");
    clamp_nonnegative_int(&cfg->deep_idle_after_ms, "deep_idle_after_ms");
    clamp_nonnegative_int(&cfg->debounce_ms, "debounce_ms");
    clamp_nonnegative_int(&cfg->debounce_count, "debounce_count");
    clamp_nonnegative_int(&cfg->startup_quiet_ms, "startup_quiet_ms");
    clamp_nonnegative_int(&cfg->settle_us, "settle_us");
    clamp_nonnegative_int(&cfg->post_row_settle_us, "post_row_settle_us");

    char tmp[32];
    json_str(buf, "row_drive",   tmp, sizeof(tmp), "output_low");
    cfg->row_drive_low = (strncmp(tmp, "output_low", 10) == 0);

    json_str(buf, "col_pull",    tmp, sizeof(tmp), "pull_up");
    cfg->col_pullup    = (strncmp(tmp, "pull_up",  7) == 0);

    json_str(buf, "key_active",  tmp, sizeof(tmp), "low");
    cfg->key_active_low= (strncmp(tmp, "low", 3) == 0);

    json_str(buf, "socket_path", cfg->socket_path,
             sizeof(cfg->socket_path), "/tmp/matrix_events.sock");
    json_str(buf, "tap_socket_path", cfg->tap_socket_path,
             sizeof(cfg->tap_socket_path), "/tmp/matrix_tap_events.sock");
    const char *event_log_path = getenv("MATRIXD_EVENT_LOG_PATH");
    if (event_log_path && event_log_path[0]) {
        snprintf(cfg->event_log_path, sizeof(cfg->event_log_path), "%s", event_log_path);
    } else {
        cfg->event_log_path[0] = '\0';
    }

    int nr = json_int_array(buf, "row_gpios", cfg->row_gpios, MAX_ROWS);
    int nc = json_int_array(buf, "col_gpios", cfg->col_gpios, MAX_COLS);

    if (cfg->matrix_enabled && (nr != cfg->rows || nc != cfg->cols)) {
        syslog(LOG_ERR, "gpio 配列長不一致 row=%d/%d col=%d/%d",
               nr, cfg->rows, nc, cfg->cols);
        return -1;
    }
    if (parse_direct_switches(buf, cfg) < 0)
        return -1;
    if (parse_rotary_encoders(buf, cfg) < 0)
        return -1;
    if (strncmp(cfg->debounce_mode, "count", 5) != 0
        && strncmp(cfg->debounce_mode, "time", 4) != 0) {
        syslog(LOG_ERR, "unknown debounce_mode=%s (expected count or time)", cfg->debounce_mode);
        return -1;
    }
    return 0;
}

/* ================================================================== */
/* GPIO 操作 (/dev/gpiomem; BCM2835 / BCM2710 共通)                    */
/* ================================================================== */

static int gpio_open(void)
{
    int fd = open("/dev/gpiomem", O_RDWR | O_SYNC);
    if (fd < 0) {
        syslog(LOG_ERR, "/dev/gpiomem を開けません: %s", strerror(errno));
        return -1;
    }
    void *m = mmap(NULL, GPIO_MAP_SIZE, PROT_READ | PROT_WRITE,
                   MAP_SHARED, fd, 0);
    close(fd);
    if (m == MAP_FAILED) {
        syslog(LOG_ERR, "mmap 失敗: %s", strerror(errno));
        return -1;
    }
    g_gpio = (volatile uint32_t *)m;
    return 0;
}

static void gpio_close(void)
{
    if (g_gpio)
        munmap((void *)g_gpio, GPIO_MAP_SIZE);
    g_gpio = NULL;
}

/* GPIO を INPUT (高インピーダンス) に設定 */
static void gpio_input(int gpio)
{
    int reg = gpio / 10;
    int bit = (gpio % 10) * 3;
    g_gpio[reg] = (g_gpio[reg] & ~(7u << bit));  /* 000 = input */
}

/* GPIO を OUTPUT に設定 */
static void gpio_output(int gpio)
{
    int reg = gpio / 10;
    int bit = (gpio % 10) * 3;
    g_gpio[reg] = (g_gpio[reg] & ~(7u << bit)) | (1u << bit);  /* 001 = output */
}

static void gpio_low (int gpio) { g_gpio[REG_GPCLR0] = (1u << gpio); }
static void gpio_high(int gpio) { g_gpio[REG_GPSET0] = (1u << gpio); }
static int  gpio_read(int gpio) { return (g_gpio[REG_GPLEV0] >> gpio) & 1; }

/* プルアップ/ダウン設定 (BCM2835 方式) */
static void gpio_pullupdown(int gpio, int pud)  /* pud: 0=off,1=down,2=up */
{
    g_gpio[REG_GPPUD]     = (uint32_t)pud;
    usleep(10);
    g_gpio[REG_GPPUDCLK0] = (1u << gpio);
    usleep(10);
    g_gpio[REG_GPPUD]     = 0;
    g_gpio[REG_GPPUDCLK0] = 0;
}

/* 全 GPIO を安全な INPUT 状態に初期化 */
static void gpio_init_all(const Config *cfg)
{
    int pud = cfg->col_pullup ? 2 : 1;
    if (cfg->matrix_enabled) {
        /* ROW 側: スキャン終了後に INPUT+PULL として待機 */
        for (int i = 0; i < cfg->rows; i++) {
            gpio_input(cfg->row_gpios[i]);
            gpio_pullupdown(cfg->row_gpios[i], pud);
        }
        /* COL 側: 通常マトリクス時は row/col が別 GPIO のため個別に初期化する。
         * チャーリープレックス時は row_gpios と同一なので重複初期化になるが無害。 */
        for (int i = 0; i < cfg->cols; i++) {
            gpio_input(cfg->col_gpios[i]);
            gpio_pullupdown(cfg->col_gpios[i], pud);
        }
    }
    for (int i = 0; i < cfg->direct_switch_count; i++) {
        gpio_input(cfg->direct_switches[i].gpio);
        gpio_pullupdown(cfg->direct_switches[i].gpio, cfg->direct_switches[i].pullup ? 2 : 1);
    }
    for (int i = 0; i < cfg->rotary_encoder_count; i++) {
        gpio_input(cfg->rotary_encoders[i].gpio_a);
        gpio_pullupdown(cfg->rotary_encoders[i].gpio_a, cfg->rotary_encoders[i].pullup ? 2 : 1);
        gpio_input(cfg->rotary_encoders[i].gpio_b);
        gpio_pullupdown(cfg->rotary_encoders[i].gpio_b, cfg->rotary_encoders[i].pullup ? 2 : 1);
    }
}

/* 終了時に全 GPIO を INPUT (pull なし) に戻す */
static void gpio_cleanup(const Config *cfg)
{
    if (cfg->matrix_enabled) {
        for (int i = 0; i < cfg->rows; i++) {
            gpio_input(cfg->row_gpios[i]);
            gpio_pullupdown(cfg->row_gpios[i], 0);
        }
        /* COL 側も解放（通常マトリクス対応; チャーリープレックス時は重複だが無害） */
        for (int i = 0; i < cfg->cols; i++) {
            gpio_input(cfg->col_gpios[i]);
            gpio_pullupdown(cfg->col_gpios[i], 0);
        }
    }
    for (int i = 0; i < cfg->direct_switch_count; i++) {
        gpio_input(cfg->direct_switches[i].gpio);
        gpio_pullupdown(cfg->direct_switches[i].gpio, 0);
    }
    for (int i = 0; i < cfg->rotary_encoder_count; i++) {
        gpio_input(cfg->rotary_encoders[i].gpio_a);
        gpio_pullupdown(cfg->rotary_encoders[i].gpio_a, 0);
        gpio_input(cfg->rotary_encoders[i].gpio_b);
        gpio_pullupdown(cfg->rotary_encoders[i].gpio_b, 0);
    }
}

/* ================================================================== */
/* マトリクス・スキャン                                                  */
/* ================================================================== */

/*
 * 1 回の全行スキャンを実行し raw[row][col] にスキャン結果 (1=押下) を書く。
 * 戻り値: 常に 0
 */
static void matrix_scan_once(const Config *cfg,
                              uint8_t raw[MAX_ROWS][MAX_COLS])
{
    int pud = cfg->col_pullup ? 2 : 1;

    for (int r = 0; r < cfg->rows; r++)
        for (int c = 0; c < cfg->cols; c++)
            raw[r][c] = 0;

    if (cfg->matrix_enabled) {
        for (int r = 0; r < cfg->rows; r++) {
            int gpio_r = cfg->row_gpios[r];

            /* ROW をドライブ前にレベルをセット (出力前の電位を確定させる) */
            if (cfg->row_drive_low)
                gpio_low(gpio_r);
            else
                gpio_high(gpio_r);

            /* ROW を OUTPUT に切り替え */
            gpio_output(gpio_r);
            usleep(cfg->settle_us);  /* セトリング待ち */

            /* 各 COL を読み取る */
            for (int c = 0; c < cfg->cols; c++) {
                if (cfg->skip_same_index && r == c) {
                    raw[r][c] = 0;
                    continue;
                }
                int level = gpio_read(cfg->col_gpios[c]);
                /* key_active_low=1: LOW(=0) で押下 */
                raw[r][c] = (uint8_t)(cfg->key_active_low ? (level == 0) : (level == 1));
            }

            /* ROW を INPUT に戻す */
            gpio_input(gpio_r);
            if (cfg->reapply_pull_each_scan)
                gpio_pullupdown(gpio_r, pud);
            usleep((useconds_t)cfg->post_row_settle_us);  /* 次の行との干渉防止 */
        }
    }

    for (int i = 0; i < cfg->direct_switch_count; i++) {
        const DirectSwitchConfig *sw = &cfg->direct_switches[i];
        int level = gpio_read(sw->gpio);
        raw[sw->row][sw->col] = (uint8_t)(sw->active_low ? (level == 0) : (level == 1));
    }

    for (int i = 0; i < cfg->rotary_encoder_count; i++) {
        const RotaryEncoderConfig *enc = &cfg->rotary_encoders[i];
        int level_a = gpio_read(enc->gpio_a);
        int level_b = gpio_read(enc->gpio_b);
        raw[enc->row_a][enc->col_a] = (uint8_t)(enc->active_low ? (level_a == 0) : (level_a == 1));
        raw[enc->row_b][enc->col_b] = (uint8_t)(enc->active_low ? (level_b == 0) : (level_b == 1));
    }
}

/* ================================================================== */
/* ソケット接続 (クライアント; logicd がサーバ)                          */
/* ================================================================== */

/*
 * socket_path の Unix ドメインソケットに接続する。
 * 失敗時は -1 を返す (再試行はメインループで行う)。
 */
static int sock_connect(const char *path)
{
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    size_t path_len = strlen(path);
    if (path_len >= sizeof(addr.sun_path)) {
        syslog(LOG_ERR, "socket path too long: %s", path);
        close(fd);
        return -1;
    }
    memcpy(addr.sun_path, path, path_len + 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int socket_path_enabled(const char *path)
{
    if (!path || path[0] == '\0') return 0;
    if (strcmp(path, "0") == 0) return 0;
    if (strcmp(path, "off") == 0) return 0;
    if (strcmp(path, "none") == 0) return 0;
    if (strcmp(path, "disabled") == 0) return 0;
    return 1;
}

static int64_t monotonic_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0)
        return 0;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int64_t monotonic_us(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0)
        return 0;
    return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}

static int64_t realtime_us(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) < 0)
        return 0;
    return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}

static void matrixd_log_event(
    const Config *cfg,
    char type,
    int row,
    int col,
    uint8_t raw,
    int64_t monotonic_event_us
)
{
    if (!cfg->event_log_path[0])
        return;

    FILE *f = fopen(cfg->event_log_path, "a");
    if (!f)
        return;
    fprintf(
        f,
        "{\"t\":\"matrixd_event\",\"unix_us\":%lld,\"monotonic_us\":%lld,"
        "\"event\":\"%c\",\"row\":%d,\"col\":%d,\"raw\":%u,\"packet\":\"%c%X%X\\n\"}\n",
        (long long)realtime_us(),
        (long long)monotonic_event_us,
        type,
        row,
        col,
        (unsigned)raw,
        type,
        row & 0xF,
        col & 0xF
    );
    fclose(f);
}

static void matrixd_log_debounce(
    const Config *cfg,
    uint64_t scan_seq,
    int row,
    int col,
    uint8_t new_raw,
    const MatrixdDebounceKey *before,
    const MatrixdDebounceKey *after,
    MatrixdDebounceEvent event,
    int64_t monotonic_event_us
)
{
    if (!cfg->event_log_path[0])
        return;
    if (before == NULL || after == NULL)
        return;
    if (new_raw == before->raw && event == MATRIXD_DEBOUNCE_EVENT_NONE)
        return;

    char event_type = 'N';
    if (event == MATRIXD_DEBOUNCE_EVENT_PRESS)
        event_type = 'P';
    else if (event == MATRIXD_DEBOUNCE_EVENT_RELEASE)
        event_type = 'R';

    FILE *f = fopen(cfg->event_log_path, "a");
    if (!f)
        return;
    fprintf(
        f,
        "{\"t\":\"matrixd_debounce\",\"unix_us\":%lld,\"monotonic_us\":%lld,"
        "\"scan\":%llu,\"row\":%d,\"col\":%d,\"new_raw\":%u,"
        "\"before\":{\"raw\":%u,\"state\":%u,\"count\":%u,\"raw_since_us\":%lld},"
        "\"after\":{\"raw\":%u,\"state\":%u,\"count\":%u,\"raw_since_us\":%lld},"
        "\"event\":\"%c\"}\n",
        (long long)realtime_us(),
        (long long)monotonic_event_us,
        (unsigned long long)scan_seq,
        row,
        col,
        (unsigned)new_raw,
        (unsigned)before->raw,
        (unsigned)before->state,
        (unsigned)before->count,
        (long long)before->raw_since_us,
        (unsigned)after->raw,
        (unsigned)after->state,
        (unsigned)after->count,
        (long long)after->raw_since_us,
        event_type
    );
    fclose(f);
}

static int scan_sleep_us(const Config *cfg, int64_t idle_ms)
{
    int interval = cfg->interval_us;

    if (cfg->deep_idle_interval_us > interval
        && cfg->deep_idle_after_ms > 0
        && idle_ms >= cfg->deep_idle_after_ms) {
        interval = cfg->deep_idle_interval_us;
    } else if (cfg->idle_interval_us > interval
               && cfg->idle_after_ms > 0
               && idle_ms >= cfg->idle_after_ms) {
        interval = cfg->idle_interval_us;
    }

    if (interval < MIN_INTERVAL_US)
        return MIN_INTERVAL_US;
    return interval;
}

/*
 * キーイベントを 4 バイトパケットで送信する。
 * 送信失敗 (接続切断など) 時は -1 を返す。
 */
static int sock_send_event(int fd, char type, int row, int col)
{
    static const char hex[] = "0123456789ABCDEF";
    char pkt[4] = {
        type,
        hex[row & 0xF],
        hex[col & 0xF],
        '\n'
    };
    ssize_t ret = send(fd, pkt, 4, MSG_NOSIGNAL);
    return (ret == 4) ? 0 : -1;
}

/* ================================================================== */
/* メインループ                                                          */
/* ================================================================== */

static void print_usage(FILE *out)
{
    fprintf(out,
            "usage: matrixd [CONFIG_JSON]\n"
            "\n"
            "Keyboard matrix scanner daemon.\n"
            "\n"
            "Arguments:\n"
            "  CONFIG_JSON   optional path to the matrixd JSON configuration\n"
            "                default: /etc/matrixd.json\n"
            "\n"
            "Options:\n"
            "  -h, --help    show this help and exit\n"
            "\n"
            "Environment:\n"
            "  MATRIXD_EVENT_LOG_PATH\n");
}

int main(int argc, char *argv[])
{
    if (argc >= 2 && (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0)) {
        print_usage(stdout);
        return 0;
    }

    /* ログ設定 */
    openlog("matrixd", LOG_PID | LOG_CONS, LOG_DAEMON);

    /* 設定ファイルパス */
    const char *config_path = (argc >= 2) ? argv[1]
                                           : "/etc/matrixd.json";

    /* シグナル設定 */
    struct sigaction sa = { .sa_handler = sig_handler };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT,  &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    /* 設定読み込み */
    Config cfg;
    memset(&cfg, 0, sizeof(cfg));
    if (config_load(config_path, &cfg) < 0)
        return 1;

    syslog(LOG_INFO, "設定読み込み完了: %dx%d matrix enabled=%d direct_switches=%d rotary_encoders=%d socket=%s tap_socket=%s",
           cfg.rows, cfg.cols, cfg.matrix_enabled, cfg.direct_switch_count,
           cfg.rotary_encoder_count, cfg.socket_path,
           socket_path_enabled(cfg.tap_socket_path) ? cfg.tap_socket_path : "disabled");

    /* GPIO 初期化 */
    if (cfg.gpio_enabled) {
        if (gpio_open() < 0)
            return 1;
        gpio_init_all(&cfg);
        syslog(LOG_INFO, "GPIO 初期化完了");
    } else {
        syslog(LOG_WARNING, "gpio_enabled=false: GPIO スキャンを無効化 (ハードウェア未接続モード)");
    }

    /* デバウンス用配列 */
    uint8_t raw[MAX_ROWS][MAX_COLS];  /* スキャン生データ */
    MatrixdDebounceKey key_state[MAX_ROWS][MAX_COLS];
    memset(raw, 0, sizeof(raw));
    for (int r = 0; r < MAX_ROWS; r++) {
        for (int c = 0; c < MAX_COLS; c++)
            matrixd_debounce_init(&key_state[r][c]);
    }

    int use_time_debounce = (strncmp(cfg.debounce_mode, "time", 4) == 0);

    /* count debounce 閾値: debounce_count が 0 より大きければそれを使用、
       それ以外は debounce_ms * 1000 / interval_us で既存互換の自動計算 */
    int debounce_thresh;
    if (cfg.debounce_count > 0) {
        debounce_thresh = cfg.debounce_count;
        if (debounce_thresh > 255) debounce_thresh = 255;
        syslog(LOG_INFO, "デバウンス閾値: %d スキャン (debounce_count 直接指定)",
               debounce_thresh);
    } else {
        debounce_thresh = (cfg.debounce_ms * 1000) / cfg.interval_us;
        if (debounce_thresh < 1) debounce_thresh = 1;
        if (debounce_thresh > 255) debounce_thresh = 255;
        syslog(LOG_INFO, "デバウンス閾値: %d スキャン (debounce_ms=%d / interval_us=%d から計算)",
               debounce_thresh, cfg.debounce_ms, cfg.interval_us);
    }
    if (use_time_debounce) {
        syslog(LOG_INFO, "デバウンス方式: time (debounce_ms=%d)", cfg.debounce_ms);
    } else {
        syslog(LOG_INFO, "デバウンス方式: count");
    }

    int sock_fd = -1;
    int tap_sock_fd = -1;
    int tap_enabled = socket_path_enabled(cfg.tap_socket_path);
    int64_t last_tap_connect_attempt_ms = 0;
    int64_t last_activity_ms = monotonic_ms();
    int64_t startup_quiet_until_us = monotonic_us() +
        (int64_t)cfg.startup_quiet_ms * 1000;
    if (cfg.startup_quiet_ms > 0)
        syslog(LOG_INFO, "起動時イベント抑止: %d ms", cfg.startup_quiet_ms);
    uint64_t scan_seq = 0;

    while (g_running) {
        /* logicd へ未接続なら接続を試みる */
        if (sock_fd < 0) {
            sock_fd = sock_connect(cfg.socket_path);
            if (sock_fd < 0) {
                /* logicd が未起動の可能性; 少し待って再試行 */
                usleep(LOGICD_CONNECT_RETRY_US);
                continue;
            }
            syslog(LOG_INFO, "logicd に接続しました: %s", cfg.socket_path);
        }

        if (tap_enabled && tap_sock_fd < 0) {
            int64_t now_ms = monotonic_ms();
            if (last_tap_connect_attempt_ms == 0 ||
                    now_ms - last_tap_connect_attempt_ms >= TAP_CONNECT_RETRY_MS) {
                last_tap_connect_attempt_ms = now_ms;
                tap_sock_fd = sock_connect(cfg.tap_socket_path);
                if (tap_sock_fd >= 0)
                    syslog(LOG_INFO, "matrix tap に接続しました: %s", cfg.tap_socket_path);
            }
        }

        /* 入力を 1 回スキャン (gpio_enabled=false 時は raw=0 のまま debounce だけ進む) */
        if (cfg.gpio_enabled)
            matrix_scan_once(&cfg, raw);
        scan_seq++;

        /* デバウンス処理とイベント送信 */
        int raw_changed = 0;
        int event_sent = 0;
        int key_active_seen = 0;
        int64_t now_us = monotonic_us();
        for (int r = 0; r < cfg.rows; r++) {
            for (int c = 0; c < cfg.cols; c++) {
                if (cfg.skip_same_index && r == c) continue;

                uint8_t new_raw = raw[r][c];
                if (new_raw || key_state[r][c].state)
                    key_active_seen = 1;
                if (new_raw != key_state[r][c].raw)
                    raw_changed = 1;

                MatrixdDebounceKey before = key_state[r][c];
                MatrixdDebounceEvent event;
                if (use_time_debounce) {
                    event = matrixd_debounce_step_time(
                        &key_state[r][c],
                        new_raw,
                        now_us,
                        (int64_t)cfg.debounce_ms * 1000
                    );
                } else {
                    event = matrixd_debounce_step_count(
                        &key_state[r][c],
                        new_raw,
                        (uint8_t)debounce_thresh
                    );
                }
                MatrixdDebounceKey after = key_state[r][c];
                matrixd_log_debounce(&cfg, scan_seq, r, c, new_raw, &before, &after, event, now_us);

                if (event != MATRIXD_DEBOUNCE_EVENT_NONE) {
                    if (now_us < startup_quiet_until_us) {
                        matrixd_debounce_commit_event(&key_state[r][c], event);
                        continue;
                    }
                    char type = (event == MATRIXD_DEBOUNCE_EVENT_PRESS) ? 'P' : 'R';
                    if (sock_send_event(sock_fd, type, r, c) < 0) {
                        syslog(LOG_WARNING, "送信失敗。再接続します");
                        close(sock_fd);
                        sock_fd = -1;
                        goto next_scan;
                    }
                    if (tap_sock_fd >= 0 && sock_send_event(tap_sock_fd, type, r, c) < 0) {
                        syslog(LOG_DEBUG, "matrix tap 送信失敗。tap 側だけ再接続します");
                        close(tap_sock_fd);
                        tap_sock_fd = -1;
                    }
                    matrixd_log_event(&cfg, type, r, c, new_raw, now_us);
                    matrixd_debounce_commit_event(&key_state[r][c], event);
                    event_sent = 1;
                }
            }
        }

        if (raw_changed || event_sent || key_active_seen)
            last_activity_ms = monotonic_ms();

next_scan:
        int64_t now_ms = monotonic_ms();
        int64_t idle_ms = now_ms - last_activity_ms;
        if (idle_ms < 0)
            idle_ms = 0;
        usleep((useconds_t)scan_sleep_us(&cfg, idle_ms));
    }

    /* クリーンアップ */
    syslog(LOG_INFO, "終了処理中…");
    if (sock_fd >= 0) close(sock_fd);
    if (tap_sock_fd >= 0) close(tap_sock_fd);
    if (cfg.gpio_enabled) {
        gpio_cleanup(&cfg);
        gpio_close();
    }
    closelog();
    return 0;
}
