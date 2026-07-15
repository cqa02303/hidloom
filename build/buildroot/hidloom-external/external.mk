# HIDloom Buildroot external tree.
#
include $(sort $(wildcard $(BR2_EXTERNAL_HIDLOOM_PATH)/package/*/*.mk))
