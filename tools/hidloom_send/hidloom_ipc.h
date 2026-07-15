#ifndef HIDLOOM_IPC_H
#define HIDLOOM_IPC_H

#include <stddef.h>

int hidloom_connect_unix(const char *path);
int hidloom_send_all(int fd, const void *buf, size_t len);

#endif
