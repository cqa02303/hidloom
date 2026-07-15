################################################################################
#
# python-luma-core
#
################################################################################

PYTHON_LUMA_CORE_VERSION = 2.5.3
PYTHON_LUMA_CORE_SOURCE = luma_core-$(PYTHON_LUMA_CORE_VERSION).tar.gz
PYTHON_LUMA_CORE_SITE = https://files.pythonhosted.org/packages/source/l/luma.core
PYTHON_LUMA_CORE_SETUP_TYPE = pep517
PYTHON_LUMA_CORE_LICENSE = MIT
PYTHON_LUMA_CORE_LICENSE_FILES = LICENSE.rst
PYTHON_LUMA_CORE_DEPENDENCIES = python-pillow python-smbus2 python-cbor2

$(eval $(python-package))
