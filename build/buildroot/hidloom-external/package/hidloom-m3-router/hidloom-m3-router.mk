HIDLOOM_M3_ROUTER_VERSION = 1
HIDLOOM_M3_ROUTER_SITE = $(BR2_EXTERNAL_HIDLOOM_PATH)/package/hidloom-m3-router/src
HIDLOOM_M3_ROUTER_SITE_METHOD = local
HIDLOOM_M3_ROUTER_LICENSE = GPL-3.0-or-later
HIDLOOM_M3_ROUTER_LICENSE_FILES = COPYING

define HIDLOOM_M3_ROUTER_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -std=c11 -D_POSIX_C_SOURCE=200809L -o $(@D)/hidloom-m3-router $(@D)/hidloom-m3-router.c
endef

define HIDLOOM_M3_ROUTER_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/hidloom-m3-router $(TARGET_DIR)/usr/bin/hidloom-m3-router
endef

$(eval $(generic-package))
