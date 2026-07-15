.PHONY: all install clean

BIN_DIR ?= ../../bin
BUILD_DIR := target/release
BIN := $(BUILD_DIR)/hidloom-uidd

all: $(BIN)

$(BIN): src/main.rs Cargo.toml Cargo.lock
	cargo build --release --locked

install: $(BIN)
	mkdir -p "$(BIN_DIR)"
	install -m 755 "$(BIN)" "$(BIN_DIR)/hidloom-uidd.tmp"
	mv -f "$(BIN_DIR)/hidloom-uidd.tmp" "$(BIN_DIR)/hidloom-uidd"

clean:
	cargo clean
