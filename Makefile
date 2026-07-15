.PHONY: cross-build-host-check rust-build rust-build-no-sccache package deb-package core-deb-package profile-deb-package touch-waveshare-profile-deb keyboard-ver1-profile-deb keyboard-ver0-profile-deb release-candidate-check release-prerelease-plan release-prerelease-publish release-download-verify release-stable-check release-deb-download release-deb-dry-run release-deb-install release-deb-deploy-dry-run release-deb-deploy deb-package-dry-run-01 deb-package-dry-run-02 deb-package-install-01 deb-package-install-02 deb-unit-switch-dry-run-01 deb-unit-switch-dry-run-02 deb-unit-switch-01 deb-unit-switch-02 deb-verify-01 deb-verify-02 deb-verify-smoke-01 deb-verify-smoke-02 deb-deploy-01 deb-deploy-02 package-dry-run-02 package-deploy-02 package-opt-dry-run-02 package-opt-deploy-02 package-deb-dry-run-02 package-deb-deploy-02 package-rollback-dry-run-02 package-rollback-02 sync-01 sync-02 deploy-01 deploy-02 smoke-01 smoke-02 boot-report boot-report-reboot boot-report-01 boot-report-02 boot-report-reboot-01 boot-report-reboot-02 docs-check

DEVICE ?= 02
DEVICE_PROFILE ?= touch-waveshare-8.8
RPI_RUST_TARGET ?= aarch64-unknown-linux-musl
RPI_01 ?= operator@<keyboard-ip>
RPI_02 ?= pi@<keyboard-ip>
BOOT_REPORT_REMOTE ?= $(if $(filter 01,$(DEVICE)),$(RPI_01),$(if $(filter 02,$(DEVICE)),$(RPI_02),$(error unknown DEVICE=$(DEVICE); use DEVICE=01 or DEVICE=02, or set BOOT_REPORT_REMOTE=user@host)))
BOOT_REPORT_LABEL ?= hidloom-$(DEVICE)
RELEASE_DEB_REMOTE_ARG = $(if $(RELEASE_DEB_REMOTE),--host "$(RELEASE_DEB_REMOTE)",--device "$(DEVICE)")

.PHONY: repository-hygiene source-syntax-hygiene development-residue-hygiene generated-binary-hygiene workspace-debris-hygiene workspace-debris-clean workspace-debris-contract local-environment-hygiene local-environment-contract local-environment-migration-plan local-environment-migration-apply public-community-health generated-artifact-check public-export-check public-repository-create-check public-repository-create-plan public-repository-create-audit public-repository-bootstrap-check public-sync-plan public-sync-branch-check public-repository-policy-plan public-repository-policy-audit public-package-rebuild public-buildroot-configure public-buildroot-image public-release-bundle-check license-evidence buildroot-source-prepare buildroot-legal-info-plan buildroot-compliance-lock buildroot-compliance-bundle buildroot-compliance-verify
PUBLIC_EXPORT_DIR ?= /tmp/hidloom-public-export
LICENSE_EVIDENCE_DIR ?= /tmp/hidloom-license-evidence
BUILDROOT_OUTPUT ?= build/artifacts/buildroot-m6-output
BUILDROOT_COMPLIANCE ?= build/artifacts/hidloom-buildroot-m6-compliance.tar.zst
LOCAL_ENV_MIGRATION_CONFIRM ?=

cross-build-host-check:
	HIDLOOM_RPI_DEVICE=$(DEVICE) tools/cross_build_host_check.sh --target $(RPI_RUST_TARGET)

repository-hygiene:
	python3 tools/repository_hygiene.py
	python3 script/test_repository_hygiene.py

source-syntax-hygiene:
	python3 tools/source_syntax_hygiene.py
	python3 script/test_source_syntax_hygiene.py

development-residue-hygiene:
	python3 tools/development_residue_hygiene.py
	python3 script/test_development_residue_hygiene.py

generated-binary-hygiene:
	python3 tools/generated_binary_hygiene.py
	python3 script/test_generated_binary_hygiene.py

workspace-debris-hygiene:
	python3 tools/workspace_debris_hygiene.py

workspace-debris-clean:
	python3 tools/workspace_debris_hygiene.py --clean

workspace-debris-contract:
	python3 script/test_workspace_debris_hygiene.py

local-environment-hygiene:
	python3 tools/local_environment_hygiene.py

local-environment-contract:
	python3 script/test_local_environment_hygiene.py

local-environment-migration-plan:
	python3 tools/local_environment_hygiene.py --rewrite-retired-keys

local-environment-migration-apply:
	@test "$(LOCAL_ENV_MIGRATION_CONFIRM)" = "REWRITE-LOCAL-ENV-KEYS" || { echo 'set LOCAL_ENV_MIGRATION_CONFIRM=REWRITE-LOCAL-ENV-KEYS' >&2; exit 1; }
	python3 tools/local_environment_hygiene.py --rewrite-retired-keys --apply --confirm "$(LOCAL_ENV_MIGRATION_CONFIRM)"

public-community-health:
	python3 tools/public_community_health.py
	python3 script/test_public_community_health.py

generated-artifact-check:
	python3 script/test_kicad_generation.py

public-export-check: repository-hygiene source-syntax-hygiene development-residue-hygiene generated-binary-hygiene workspace-debris-hygiene workspace-debris-contract local-environment-contract public-community-health generated-artifact-check
	python3 tools/public_export.py $(PUBLIC_EXPORT_DIR) --draft --force
	python3 script/test_public_export.py
	python3 script/test_public_export_bundle.py
	python3 script/test_public_buildroot_rebuild.py
	python3 script/test_public_reference_audit.py
	python3 script/test_buildroot_compliance_bundle.py
	python3 script/test_public_release_bundle.py
	python3 script/test_public_repository_create.py
	python3 script/test_public_repository_bootstrap.py
	python3 script/test_public_sync_branch.py
	python3 script/test_public_release_readiness.py
	python3 script/test_public_repository_policy.py
	python3 $(PUBLIC_EXPORT_DIR)/tools/public_release_readiness.py $(PUBLIC_EXPORT_DIR) --allow-pending-pid

public-sync-plan: public-export-check
	python3 $(PUBLIC_EXPORT_DIR)/tools/public_sync_plan.py $(PUBLIC_EXPORT_DIR) --allow-pending-pid

public-repository-create-check:
	python3 script/test_public_repository_create.py

public-repository-create-plan:
	python3 tools/public_repository_create.py plan

public-repository-create-audit:
	python3 tools/public_repository_create.py audit

public-repository-bootstrap-check:
	python3 script/test_public_repository_bootstrap.py

public-sync-branch-check:
	python3 script/test_public_sync_branch.py

public-repository-policy-plan:
	python3 tools/public_repository_policy.py plan

public-repository-policy-audit:
	python3 tools/public_repository_policy.py audit

public-package-rebuild:
	tools/public_build_rehearsal.sh --package

public-buildroot-configure:
	tools/public_build_rehearsal.sh --buildroot-configure

public-buildroot-image:
	tools/public_build_rehearsal.sh --buildroot-image

public-release-bundle-check:
	python3 script/test_buildroot_compliance_bundle.py
	python3 script/test_public_release_bundle.py

license-evidence:
	python3 tools/collect_license_evidence.py $(LICENSE_EVIDENCE_DIR)

buildroot-legal-info-plan:
	python3 tools/buildroot_legal_info.py --output $(BUILDROOT_OUTPUT)

buildroot-compliance-lock:
	python3 tools/buildroot_compliance_bundle.py lock --refresh

buildroot-compliance-bundle:
	python3 tools/buildroot_compliance_bundle.py build --fetch-missing --output $(BUILDROOT_COMPLIANCE)

buildroot-compliance-verify:
	python3 tools/buildroot_compliance_bundle.py verify $(BUILDROOT_COMPLIANCE)

rust-build:
	tools/build_rpi_rust.sh --target $(RPI_RUST_TARGET)

rust-build-no-sccache:
	tools/build_rpi_rust.sh --target $(RPI_RUST_TARGET) --no-sccache

package:
	tools/package/build_release_bundle.sh --allow-dirty

deb-package:
	tools/package/build_deb_package.sh --build-bundle

core-deb-package:
	tools/package/build_deb_package.sh --build-bundle --package-id hidloom-core

profile-deb-package:
	tools/package/build_device_profile_deb.sh --profile $(DEVICE_PROFILE)

touch-waveshare-profile-deb:
	$(MAKE) DEVICE_PROFILE=touch-waveshare-8.8 profile-deb-package

keyboard-ver1-profile-deb:
	$(MAKE) DEVICE_PROFILE=keyboard-ver1 profile-deb-package

keyboard-ver0-profile-deb:
	$(MAKE) DEVICE_PROFILE=keyboard-ver0-prototype profile-deb-package

release-candidate-check:
	tools/package/release_candidate_check.sh

release-prerelease-plan:
	tools/package/publish_github_prerelease.sh

release-prerelease-publish:
	tools/package/publish_github_prerelease.sh --execute

release-download-verify:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/verify_github_release_assets.sh --tag "$(RELEASE_TAG)"

release-stable-check:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/check_github_release_stable_ready.sh --tag "$(RELEASE_TAG)"

release-deb-download:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/install_github_release_deb.sh --tag "$(RELEASE_TAG)"

release-deb-dry-run:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/install_github_release_deb.sh --tag "$(RELEASE_TAG)" $(RELEASE_DEB_REMOTE_ARG) --dry-run

release-deb-install:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/install_github_release_deb.sh --tag "$(RELEASE_TAG)" $(RELEASE_DEB_REMOTE_ARG) --install

release-deb-deploy-dry-run:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/deploy_github_release_deb.sh --tag "$(RELEASE_TAG)" $(RELEASE_DEB_REMOTE_ARG) --dry-run

release-deb-deploy:
	@if [ -z "$(RELEASE_TAG)" ]; then echo "set RELEASE_TAG=v0.0.<rev>+git<sha>"; exit 2; fi
	tools/package/deploy_github_release_deb.sh --tag "$(RELEASE_TAG)" $(RELEASE_DEB_REMOTE_ARG) --install

deb-package-dry-run-01:
	tools/package/deploy_deb_package.sh --device 01 --dry-run --apt

deb-package-dry-run-02:
	tools/package/deploy_deb_package.sh --device 02 --dry-run --apt

deb-package-install-01:
	tools/package/deploy_deb_package.sh --device 01 --install --apt

deb-package-install-02:
	tools/package/deploy_deb_package.sh --device 02 --install --apt

deb-unit-switch-dry-run-01:
	tools/package/deploy_deb_unit_switch.sh --device 01 --dry-run

deb-unit-switch-dry-run-02:
	tools/package/deploy_deb_unit_switch.sh --device 02 --dry-run

deb-unit-switch-01:
	tools/package/deploy_deb_unit_switch.sh --device 01 --restart

deb-unit-switch-02:
	tools/package/deploy_deb_unit_switch.sh --device 02 --restart

deb-verify-01:
	tools/package/deploy_deb_verify.sh --device 01

deb-verify-02:
	tools/package/deploy_deb_verify.sh --device 02

deb-verify-smoke-01:
	tools/package/deploy_deb_verify.sh --device 01 --smoke

deb-verify-smoke-02:
	tools/package/deploy_deb_verify.sh --device 02 --smoke

deb-deploy-01: deb-package deb-package-install-01 deb-unit-switch-01 deb-verify-smoke-01

deb-deploy-02: deb-package deb-package-install-02 deb-unit-switch-02 deb-verify-smoke-02

package-dry-run-02:
	tools/package/deploy_release_bundle.sh --device 02 --dry-run

package-deploy-02:
	tools/package/deploy_release_bundle.sh --device 02 --restart

package-opt-dry-run-02:
	tools/package/deploy_release_bundle.sh --device 02 --opt-release --dry-run

package-opt-deploy-02:
	tools/package/deploy_release_bundle.sh --device 02 --opt-release --restart

package-deb-dry-run-02:
	tools/package/deploy_release_bundle.sh --device 02 --deb-layout --dry-run

package-deb-deploy-02:
	tools/package/deploy_release_bundle.sh --device 02 --deb-layout --restart

package-rollback-dry-run-02:
	tools/package/deploy_release_rollback.sh --device 02 --previous --dry-run

package-rollback-02:
	tools/package/deploy_release_rollback.sh --device 02 --previous --restart

sync-01:
	tools/sync_rpi_checkout.sh --device 01

sync-02:
	tools/sync_rpi_checkout.sh --device 02

deploy-01:
	tools/deploy_rpi_rust.sh --device 01 --target $(RPI_RUST_TARGET) --restart

deploy-02:
	tools/deploy_rpi_rust.sh --device 02 --target $(RPI_RUST_TARGET) --restart

smoke-01:
	tools/deploy_rpi_rust.sh --device 01 --target $(RPI_RUST_TARGET) --smoke

smoke-02:
	tools/deploy_rpi_rust.sh --device 02 --target $(RPI_RUST_TARGET) --smoke

boot-report:
	python3 tools/remote_boot_baseline_collect.py $(BOOT_REPORT_REMOTE) --label $(BOOT_REPORT_LABEL) --samples 1 --sudo

boot-report-reboot:
	python3 tools/remote_boot_baseline_collect.py $(BOOT_REPORT_REMOTE) --label $(BOOT_REPORT_LABEL) --samples 1 --sudo --reboot-before-sample

boot-report-01:
	$(MAKE) DEVICE=01 boot-report

boot-report-02:
	$(MAKE) DEVICE=02 boot-report

boot-report-reboot-01:
	$(MAKE) DEVICE=01 boot-report-reboot

boot-report-reboot-02:
	$(MAKE) DEVICE=02 boot-report-reboot

docs-check:
	python3 script/test_docs_links.py
	python3 script/test_tools_readme.py
buildroot-source-prepare:
	python3 tools/buildroot_source_prepare.py
