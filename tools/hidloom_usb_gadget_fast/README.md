# hidloom-usb-gadget-fast

Native fast-path helper for the normal CQA02303v5 USB HID gadget setup.

This helper is intentionally narrower than `system/install/setup_usb_gadget.sh`.
It creates the production composite gadget with fixed descriptors and a small
set of environment overrides. Flexible profile experiments and unusual host
identity tests remain in the shell fallback.

Supported fast-path interfaces:

- `hid.usb0`: keyboard + mouse + consumer multi-report
- `hid.usb1`: Raw HID / Vial
- `hid.usb2`: US sub keyboard, enabled by default

Environment:

- `HIDLOOM_USB_GADGET_ROOT` defaults to `/sys/kernel/config/usb_gadget`
- `HIDLOOM_USB_VENDOR_ID` defaults to `0x1d6b`
- `HIDLOOM_USB_PRODUCT_ID` defaults to `0x0105`
- `HIDLOOM_USB_MANUFACTURER` defaults to the hostname
- `HIDLOOM_USB_PRODUCT_NAME` defaults to the hostname
- `HIDLOOM_USB_SERIAL` defaults to the Vial serial magic
- `HIDLOOM_USB_SERIAL_SUFFIX` appends to `vial:f64c2b3c`
- `HIDLOOM_USB_US_SUB_KEYBOARD` defaults to enabled
- `HIDLOOM_WINDOWS_IME_CUSTOM_HID` can enable the optional `hid.usb4`

Use `HIDLOOM_USB_GADGET_SETUP_BACKEND=native` in the systemd unit wrapper once the
helper has been built into `bin/hidloom-usb-gadget-fast`.
