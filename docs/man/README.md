# Manual Pages

This directory contains source manual pages that are installed into Debian
packages under `/usr/share/man`.

The pages intentionally stay small:

- `man1`: operator/helper commands
- `man5`: stable configuration file entrypoints
- `man8`: daemons and package-managed services

`tools/package/build_deb_package.sh` expands these placeholders while building
the package:

- `@HIDLOOM_VERSION@`
- `@HIDLOOM_GIT_SHA@`

Keep detailed design notes in `docs/` and link to GitHub from `SEE ALSO`
instead of duplicating long design text in man pages.

まず見る文書:

文書一覧:
