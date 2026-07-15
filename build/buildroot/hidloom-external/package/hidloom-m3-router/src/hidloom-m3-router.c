#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;
static void stop(int sig) { (void)sig; running = 0; }

static void marker(const char *name) {
    FILE *uptime = fopen("/proc/uptime", "r");
    FILE *out = fopen("/tmp/hidloom-boot-markers.log", "a");
    double sec = 0.0;
    if (uptime) { fscanf(uptime, "%lf", &sec); fclose(uptime); }
    if (out) { fprintf(out, "%.6f %s\n", sec, name); fclose(out); }
}

static int report(int hid, uint8_t usage) {
    uint8_t data[8] = {0};
    data[2] = usage;
    return write(hid, data, sizeof(data)) == (ssize_t)sizeof(data) ? 0 : -1;
}

int main(void) {
    const char *path = "/tmp/matrix_events.sock";
    int server = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);
    signal(SIGINT, stop); signal(SIGTERM, stop);
    unlink(path);
    if (server < 0 || bind(server, (struct sockaddr *)&addr, sizeof(addr)) || listen(server, 1)) return 1;
    marker("m3_router_ready");
    while (running) {
        int client = accept(server, NULL, NULL);
        if (client < 0) { if (errno == EINTR) continue; break; }
        marker("m3_matrix_connected");
        int hid = open("/dev/hidg0", O_WRONLY);
        char packet[4];
        while (running && hid >= 0 && read(client, packet, sizeof(packet)) == sizeof(packet)) {
            if (packet[0] == 'P') { marker("m3_physical_press"); if (!report(hid, 0x04)) marker("m3_hid_report_sent"); }
            if (packet[0] == 'R') { report(hid, 0x00); marker("m3_physical_release"); }
        }
        if (hid >= 0) { report(hid, 0); close(hid); }
        close(client);
    }
    close(server); unlink(path); return 0;
}
