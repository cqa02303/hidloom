.PHONY: all install clean

BIN_DIR ?= ../../bin
BUILD_DIR := target/release
BIN := $(BUILD_DIR)/hidloom-outputd

all: $(BIN)

$(BIN): src/main.rs Cargo.toml Cargo.lock
	cargo build --release --locked

install: $(BIN)
	mkdir -p "$(BIN_DIR)"
	install -m 755 "$(BIN)" "$(BIN_DIR)/hidloom-outputd.tmp"
	mv -f "$(BIN_DIR)/hidloom-outputd.tmp" "$(BIN_DIR)/hidloom-outputd"

clean:
	cargo clean
