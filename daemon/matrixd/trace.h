#ifndef HIDLOOM_MATRIXD_TRACE_H
#define HIDLOOM_MATRIXD_TRACE_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define MATRIXD_TRACE_DEFAULT_MAX_FILE_BYTES (4U * 1024U * 1024U)
#define MATRIXD_TRACE_MAX_RECORD_BYTES 2048U

typedef struct {
    volatile uint64_t records_written;
    volatile uint64_t bytes_written;
    volatile uint64_t rotations;
    volatile uint64_t io_errors;
} MatrixdTraceWriterCounters;

typedef struct {
    int write_fd;
    pid_t writer_pid;
    uint64_t records_queued;
    uint64_t queue_dropped;
    MatrixdTraceWriterCounters *writer;
} MatrixdTrace;

int matrixd_trace_start(MatrixdTrace *trace, const char *path, size_t max_file_bytes);
int matrixd_trace_emit(MatrixdTrace *trace, const char *record, size_t length);
void matrixd_trace_stop(MatrixdTrace *trace);

#endif
