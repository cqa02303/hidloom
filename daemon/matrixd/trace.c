#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE

#include "trace.h"

#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

#define TRACE_PATH_BYTES 256
#define TRACE_READ_BYTES 4096
#define TRACE_PENDING_BYTES (TRACE_READ_BYTES + MATRIXD_TRACE_MAX_RECORD_BYTES)
#define TRACE_ERROR_LOG_INTERVAL_SEC 60

static int rotated_path(const char *path, char *out, size_t out_size)
{
    const char suffix[] = ".jsonl";
    size_t path_len = strlen(path);
    size_t suffix_len = sizeof(suffix) - 1;
    int written;

    if (path_len >= suffix_len && strcmp(path + path_len - suffix_len, suffix) == 0) {
        written = snprintf(out, out_size, "%.*s.1%s",
                           (int)(path_len - suffix_len), path, suffix);
    } else {
        written = snprintf(out, out_size, "%s.1", path);
    }
    return written >= 0 && (size_t)written < out_size ? 0 : -1;
}

static void rate_limited_writer_error(const char *operation, const char *path)
{
    static time_t last_log;
    time_t now = time(NULL);
    if (last_log == 0 || now - last_log >= TRACE_ERROR_LOG_INTERVAL_SEC) {
        syslog(LOG_WARNING, "diagnostic trace %s failed for %s: %s",
               operation, path, strerror(errno));
        last_log = now;
    }
}

static int normalized_existing_size(const char *path, size_t max_file_bytes, off_t *size_out)
{
    struct stat st;
    if (lstat(path, &st) < 0) {
        if (errno == ENOENT) {
            *size_out = 0;
            return 0;
        }
        return -1;
    }
    if (!S_ISREG(st.st_mode) || st.st_size < 0 || (uint64_t)st.st_size > max_file_bytes) {
        if (unlink(path) < 0)
            return -1;
        *size_out = 0;
        return 0;
    }
    if (chmod(path, 0600) < 0)
        return -1;
    *size_out = st.st_size;
    return 0;
}

static int open_trace_file(const char *path, off_t *size_out)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0)
        return -1;
    if (fchmod(fd, 0600) < 0) {
        close(fd);
        return -1;
    }
    off_t current = lseek(fd, 0, SEEK_END);
    if (current < 0) {
        close(fd);
        return -1;
    }
    *size_out = current;
    return fd;
}

static int rotate_trace(const char *path, const char *rotated,
                        size_t max_file_bytes, off_t *size_out)
{
    off_t ignored;
    if (normalized_existing_size(rotated, max_file_bytes, &ignored) < 0)
        return -1;
    if (unlink(rotated) < 0 && errno != ENOENT)
        return -1;
    if (rename(path, rotated) < 0 && errno != ENOENT)
        return -1;
    if (chmod(rotated, 0600) < 0 && errno != ENOENT)
        return -1;
    *size_out = 0;
    return 0;
}

static int write_all(int fd, const char *buffer, size_t length)
{
    size_t offset = 0;
    while (offset < length) {
        ssize_t count = write(fd, buffer + offset, length - offset);
        if (count > 0) {
            offset += (size_t)count;
            continue;
        }
        if (count < 0 && errno == EINTR)
            continue;
        return -1;
    }
    return 0;
}

static void writer_loop(int read_fd, const char *path, size_t max_file_bytes,
                        MatrixdTraceWriterCounters *counters)
{
    char rotated[TRACE_PATH_BYTES];
    char buffer[TRACE_READ_BYTES];
    char pending[TRACE_PENDING_BYTES];
    size_t pending_length = 0;
    off_t current_size = 0;
    int output_fd = -1;

    signal(SIGTERM, SIG_IGN);
    signal(SIGINT, SIG_IGN);
    (void)prctl(PR_SET_NAME, "matrixd-trace", 0, 0, 0);
    struct sched_param normal_priority = {0};
    (void)sched_setscheduler(0, SCHED_OTHER, &normal_priority);
    (void)setpriority(PRIO_PROCESS, 0, 0);

    if (rotated_path(path, rotated, sizeof(rotated)) < 0) {
        counters->io_errors++;
        close(read_fd);
        _exit(0);
    }
    if (normalized_existing_size(path, max_file_bytes, &current_size) < 0) {
        counters->io_errors++;
        current_size = 0;
    }
    off_t rotated_size = 0;
    if (normalized_existing_size(rotated, max_file_bytes, &rotated_size) < 0)
        counters->io_errors++;

    for (;;) {
        ssize_t count = read(read_fd, buffer, sizeof(buffer));
        if (count == 0)
            break;
        if (count < 0) {
            if (errno == EINTR)
                continue;
            counters->io_errors++;
            rate_limited_writer_error("read", path);
            break;
        }
        if (pending_length + (size_t)count > sizeof(pending)) {
            counters->io_errors++;
            pending_length = 0;
            continue;
        }
        memcpy(pending + pending_length, buffer, (size_t)count);
        pending_length += (size_t)count;
        size_t consumed = 0;
        for (size_t i = 0; i < pending_length; i++) {
            if (pending[i] != '\n')
                continue;
            size_t record_length = i + 1 - consumed;
            if (record_length > max_file_bytes) {
                counters->io_errors++;
                consumed = i + 1;
                continue;
            }
            if ((uint64_t)current_size + record_length > max_file_bytes) {
                if (output_fd >= 0) {
                    close(output_fd);
                    output_fd = -1;
                }
                if (rotate_trace(path, rotated, max_file_bytes, &current_size) < 0) {
                    counters->io_errors++;
                    rate_limited_writer_error("rotate", path);
                    consumed = i + 1;
                    continue;
                }
                counters->rotations++;
            }
            if (output_fd < 0) {
                output_fd = open_trace_file(path, &current_size);
                if (output_fd < 0) {
                    counters->io_errors++;
                    rate_limited_writer_error("open", path);
                    consumed = i + 1;
                    continue;
                }
            }
            if (write_all(output_fd, pending + consumed, record_length) < 0) {
                counters->io_errors++;
                rate_limited_writer_error("write", path);
                close(output_fd);
                output_fd = -1;
                consumed = i + 1;
                continue;
            }
            current_size += (off_t)record_length;
            counters->bytes_written += (uint64_t)record_length;
            counters->records_written++;
            consumed = i + 1;
        }
        if (consumed > 0) {
            memmove(pending, pending + consumed, pending_length - consumed);
            pending_length -= consumed;
        }
    }
    if (output_fd >= 0)
        close(output_fd);
    close(read_fd);
    _exit(0);
}

int matrixd_trace_start(MatrixdTrace *trace, const char *path, size_t max_file_bytes)
{
    int pipe_fds[2] = {-1, -1};
    memset(trace, 0, sizeof(*trace));
    trace->write_fd = -1;
    trace->writer_pid = -1;
    if (!path || !path[0])
        return 0;
    if (strlen(path) >= TRACE_PATH_BYTES || max_file_bytes < MATRIXD_TRACE_MAX_RECORD_BYTES)
        return -1;

    trace->writer = mmap(NULL, sizeof(*trace->writer), PROT_READ | PROT_WRITE,
                         MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (trace->writer == MAP_FAILED) {
        trace->writer = NULL;
        return -1;
    }
    memset((void *)trace->writer, 0, sizeof(*trace->writer));
    if (pipe(pipe_fds) < 0)
        goto fail;
    int flags = fcntl(pipe_fds[1], F_GETFL, 0);
    if (flags < 0 || fcntl(pipe_fds[1], F_SETFL, flags | O_NONBLOCK) < 0)
        goto fail;
    pid_t pid = fork();
    if (pid < 0)
        goto fail;
    if (pid == 0) {
        close(pipe_fds[1]);
        writer_loop(pipe_fds[0], path, max_file_bytes, trace->writer);
    }
    close(pipe_fds[0]);
    trace->write_fd = pipe_fds[1];
    trace->writer_pid = pid;
    return 0;

fail:
    if (pipe_fds[0] >= 0)
        close(pipe_fds[0]);
    if (pipe_fds[1] >= 0)
        close(pipe_fds[1]);
    munmap((void *)trace->writer, sizeof(*trace->writer));
    trace->writer = NULL;
    return -1;
}

int matrixd_trace_emit(MatrixdTrace *trace, const char *record, size_t length)
{
    if (!trace || trace->write_fd < 0)
        return 0;
    if (!record || length == 0 || length > MATRIXD_TRACE_MAX_RECORD_BYTES || record[length - 1] != '\n') {
        trace->queue_dropped++;
        return -1;
    }
    ssize_t count = write(trace->write_fd, record, length);
    if (count == (ssize_t)length) {
        trace->records_queued++;
        return 0;
    }
    trace->queue_dropped++;
    return -1;
}

void matrixd_trace_stop(MatrixdTrace *trace)
{
    if (!trace)
        return;
    if (trace->write_fd >= 0) {
        close(trace->write_fd);
        trace->write_fd = -1;
    }
    if (trace->writer_pid > 0) {
        while (waitpid(trace->writer_pid, NULL, 0) < 0 && errno == EINTR) {
        }
        trace->writer_pid = -1;
    }
    if (trace->writer) {
        munmap((void *)trace->writer, sizeof(*trace->writer));
        trace->writer = NULL;
    }
}
