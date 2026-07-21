# HIDloom Authorship and Copyright

HIDloom uses an individual-contributor copyright model. Copyright in each
contribution remains with its author unless a separate written agreement says
otherwise. The project does not require copyright assignment.

`HIDloom contributors` is the collective public notice for those individual
copyright holders; it does not create a separate legal entity or transfer any
rights. The project is maintained through the
[project maintainer account](https://github.com/cqa02303/).

Contributions are accepted under [`GPL-3.0-or-later`](LICENSE) as described in
[`CONTRIBUTING.md`](CONTRIBUTING.md). Third-party material remains subject to
its own attribution and license terms in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Acknowledgements

HIDloom's keyboard behavior, keycode support, Raw HID interoperability, and
lighting compatibility have benefited from the specifications and open-source
implementations published by the following projects:

- [Vial](https://get.vial.today/) — including
  [vial-qmk](https://github.com/vial-kb/vial-qmk) and
  [vial-gui](https://github.com/vial-kb/vial-gui), which provide the protocol
  and implementation references used to maintain Vial and VialRGB
  compatibility.
- [QMK Firmware](https://github.com/qmk/qmk_firmware) and the
  [QMK documentation](https://docs.qmk.fm/), which provide the keycode,
  layer, and keyboard-behavior references used when designing compatible
  HIDloom behavior.
- [keypos](https://github.com/nickcoutsos/keypos) by
  [Nick Coutsos](https://github.com/nickcoutsos), whose KLE layout parsing
  approach was used as a reference for HIDloom's simplified browser-side KLE
  parser.

We sincerely thank the Vial and QMK maintainers and contributors, and Nick
Coutsos, for making these valuable implementations and documentation openly
available. These projects are upstream references and independent projects;
their inclusion here does not imply endorsement of HIDloom.
