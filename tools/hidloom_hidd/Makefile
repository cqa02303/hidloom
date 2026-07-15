BUILD_DIR ?= target/release
REPO_ROOT := $(abspath ../..)
BIN_DIR ?= $(REPO_ROOT)/bin
CARGO ?= cargo

BIN := $(BUILD_DIR)/hidloom-hidd

.PHONY: all clean install

all: $(BIN)

$(BIN): src/main.rs Cargo.toml Cargo.lock
	$(CARGO) build --release --locked

install: all
	mkdir -p "$(BIN_DIR)"
	install -m 755 "$(BIN)" "$(BIN_DIR)/hidloom-hidd.tmp"
	mv -f "$(BIN_DIR)/hidloom-hidd.tmp" "$(BIN_DIR)/hidloom-hidd"

clean:
	$(CARGO) clean
