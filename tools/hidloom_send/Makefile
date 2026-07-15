BUILD_DIR ?= .build
REPO_ROOT := $(abspath ../..)
BIN_DIR ?= $(REPO_ROOT)/bin
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -std=c11
CPPFLAGS ?=
LDFLAGS ?=

COMMON_OBJS := $(BUILD_DIR)/hidloom_ipc.o $(BUILD_DIR)/hidloom_keyevent.o
BINS := $(BUILD_DIR)/hidloom-key $(BUILD_DIR)/hidloom-keytext $(BUILD_DIR)/hidloom-oled $(BUILD_DIR)/hidloom-notify $(BUILD_DIR)/hidloom-ctrl

.PHONY: all clean install

all: $(BINS)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/hidloom-key: hidloom_key.c $(COMMON_OBJS) | $(BUILD_DIR)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD_DIR)/hidloom-keytext: hidloom_keytext.c $(COMMON_OBJS) | $(BUILD_DIR)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD_DIR)/hidloom-oled: hidloom_oled.c $(BUILD_DIR)/hidloom_ipc.o | $(BUILD_DIR)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD_DIR)/hidloom-notify: hidloom_notify.c $(BUILD_DIR)/hidloom_ipc.o | $(BUILD_DIR)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

$(BUILD_DIR)/hidloom-ctrl: hidloom_ctrl.c $(BUILD_DIR)/hidloom_ipc.o | $(BUILD_DIR)
	$(CC) $(CFLAGS) $^ $(LDFLAGS) -o $@

install: all
	mkdir -p $(BIN_DIR)
	cp $(BINS) $(BIN_DIR)/
	chmod 755 $(BIN_DIR)/hidloom-key $(BIN_DIR)/hidloom-keytext $(BIN_DIR)/hidloom-oled $(BIN_DIR)/hidloom-notify $(BIN_DIR)/hidloom-ctrl

clean:
	rm -rf $(BUILD_DIR)
