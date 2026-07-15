# matrixd Makefile
#
# ネイティブビルド (Raspberry Pi 上):
#   make
#
# クロスコンパイル (Buildroot 環境):
#   make CC=arm-buildroot-linux-gnueabihf-gcc

CC      ?= gcc
CFLAGS  := -std=c11 -Wall -Wextra -O2 -D_POSIX_C_SOURCE=200809L
TARGET  := matrixd
SRC     := matrixd.c debounce.c

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $(SRC)

install: $(TARGET)
	install -m 755 $(TARGET) /usr/local/sbin/$(TARGET)

clean:
	rm -f $(TARGET)
