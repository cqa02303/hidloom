# Security Policy

## Supported versions

Before the first public release, security fixes are prepared on the latest `main` revision only.
After public releases begin, the newest release line and `main` are supported unless a release note says otherwise.

## Reporting a vulnerability

Do not open a public issue for an unpatched vulnerability, credential, private key, or device-specific secret.

Use GitHub private vulnerability reporting for the public HIDloom repository. If that feature is temporarily
unavailable, open a public issue containing only a request for a private security contact; do not include exploit
details or sensitive data.

Include, when possible:

- affected revision or release;
- affected runtime: Raspberry Pi OS, Buildroot, or both;
- reproducible steps with secrets and private network details removed;
- expected impact and whether physical access is required;
- a proposed fix or regression test, if available.

The project will acknowledge a private report, reproduce it, prepare a fix and release note, and coordinate
disclosure timing with the reporter. No response-time guarantee is offered before a maintained public release exists.

## Security boundaries

- HIDloom can emit keyboard, mouse, consumer-control, and local uinput events. Treat configuration and scripts as code.
- The Raspberry Pi OS profile may expose HTTPS, SSH, Bluetooth, and local Unix sockets according to deployment config.
- The Buildroot profile is an offline keyboard appliance and intentionally omits Wi-Fi and HTTP services.
- Example credentials in experimental images must be changed before use outside an isolated test setup.
- Public reports and logs must replace hostnames, addresses, usernames, serials, and key material with placeholders.

## Experimental Buildroot credentials

The current experimental M6 Buildroot image creates the local console account `pi` with the initial password `pi`.
The image is designed as an offline keyboard appliance without Wi-Fi or HTTP services, but the credential is still
unsafe for a networked or shared deployment. Change or disable it before enabling any additional access path. Release
notes for an image carrying this account must repeat this warning.

## Build and CI supply chain

- Every external action in `.github/workflows` is pinned to a reviewed full-length commit SHA. Mutable tags and
  unreviewed action repositories are rejected by `script/test_github_workflow_security.py`.
- `config/github-actions-lock.json` records the matching release, commit, and license. A workflow reference and its
  lock entry must be updated together after reviewing the upstream release.
- `.github/dependabot.yml` checks GitHub Actions weekly, but an update is not accepted until the lock and regression
  suite agree. Publicly shipped action references are also listed in the CycloneDX SBOM as non-redistributed CI dependencies.
- Public export artifacts are uploaded as a manifest-bounded deterministic `tar.zst`, not as a raw directory. This
  preserves executable bits and dotfiles such as `.github` while excluding files outside the audited manifest. Regular
  file modes are normalized to `0644`/`0755`, so the host umask cannot alter the archive.
- Before publication, enable the repository setting that requires actions to be pinned to a full-length commit SHA.

## Scope

Security reports about HIDloom source, release artifacts, build helpers, default configuration, and documented deployment
are in scope. Vulnerabilities in upstream Linux, Buildroot, BusyBox, Python, Rust crates, firmware, or hardware should
also be reported upstream; report them to HIDloom when its packaging or configuration makes the issue exploitable.
