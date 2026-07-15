BUILD_DIR ?= .build
REPO_ROOT := $(abspath ../..)
BIN_DIR ?= $(REPO_ROOT)/bin
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -std=c11 -D_POSIX_C_SOURCE=200809L
LDFLAGS ?=

BIN := $(BUILD_DIR)/hidloom-usb-gadget-fast

.PHONY: all clean install

all: $(BIN)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BIN): hidloom_usb_gadget_fast.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) $< $(LDFLAGS) -o $@

install: all
	mkdir -p "$(BIN_DIR)"
	install -m 755 $(BIN) "$(BIN_DIR)/hidloom-usb-gadget-fast.tmp"
	mv -f "$(BIN_DIR)/hidloom-usb-gadget-fast.tmp" "$(BIN_DIR)/hidloom-usb-gadget-fast"

clean:
	rm -rf $(BUILD_DIR)
