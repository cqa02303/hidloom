BUILD_DIR ?= target/release
REPO_ROOT := $(abspath ../..)
BIN_DIR ?= $(REPO_ROOT)/bin
CARGO ?= cargo

BIN := $(BUILD_DIR)/hidloom-logicd-core

.PHONY: all test clean install

all: $(BIN)

$(BIN): src/main.rs Cargo.toml Cargo.lock
	$(CARGO) build --release --locked

test:
	$(CARGO) test --locked

install: all
	mkdir -p "$(BIN_DIR)"
	install -m 755 "$(BIN)" "$(BIN_DIR)/hidloom-logicd-core.tmp"
	mv -f "$(BIN_DIR)/hidloom-logicd-core.tmp" "$(BIN_DIR)/hidloom-logicd-core"

clean:
	$(CARGO) clean
