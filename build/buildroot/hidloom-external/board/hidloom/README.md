# HIDloom Buildroot overlay for cqa02303v5

This board directory is intentionally minimal.

M1 creates only a single boot-protocol USB HID keyboard function at `/dev/hidg0`.
It is meant to answer one question first: how quickly can the Pi enumerate as a usable keyboard
when the full Raspberry Pi OS userspace is removed?

Do not add Python daemons, BlueZ, HTTP, Vial, OLED, or LED dependencies to this first slice.
Those belong to later M3-M5 phases after the M1 boot marker is measured.
