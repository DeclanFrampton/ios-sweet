# iOS Sweet Studio: component provenance

The public installer contains this project's source-built development helpers,
open-source emulation/preparation tools and their runtime dependencies. It
contains **no Apple iOS filesystem, IPSW, Apple SDK, Apple account key, private
IPA, device identifier or prepared guest disk**. Firmware is downloaded by the
user directly from Apple or imported from the user's local prepared image.

## Open-source components

* iOS Sweet and the patched XNU kernel: see the repository LICENSE,
  `xnu/patches/`, `.github/workflows/xnu.yml`, and Apple's published XNU source.
  Kernel SHA-256 is pinned in `runtime_setup.py` and the packaged manifest.
* QEMU: GNU GPL version 2; the original `COPYING`, `COPYING.LIB`, and README
  are in `desktop/assets/qemu`. This preview uses the tested Windows build
  `11.1.0 (v11.1.0-12130-ge470268ff4)`; it is not a macOS/CoreSimulator binary.
  Upstream source: https://gitlab.com/qemu-project/qemu
  Windows build distribution and build/source information: https://qemu.weilnetz.de/
* Linux preparation kernel/modules: Ubuntu `6.8.0-147-generic`; original
  copyright and exact package inventory are in `desktop/assets/licenses`.
  Corresponding source packages: https://launchpad.net/ubuntu/+source/linux
* apfs-fuse: https://github.com/sgan81/apfs-fuse at
  `66b86bd525e8cb90f9012543be89b1f092b75cf3`; original license is included.
* BusyBox, hfsprogs, rsync, Python and their shared-library dependencies: the
  preparation appliance is built from Ubuntu 24.04 packages. See the included
  package inventory and `desktop/appliance/` for the complete build recipe.
* apple-codesign 0.29.0: https://github.com/indygreg/apple-platform-rs
  The Windows asset is downloaded from its official release, SHA-256
  `fd5aeb908f1d3be60f7e372003772f52a6ce4148106d3aaf22aec6861f5d8a5e`.
  Signing is local/ad-hoc; no Apple account or signing certificate is used.
* pywebview, Python.NET, LIEF, Pillow and PyInstaller: exact versions are in
  `desktop/requirements.txt`; upstream package license files accompany the
  frozen application. WebView2, when missing, is obtained directly from
  Microsoft and its Authenticode signature is checked before installation.

All original component licenses remain applicable. The Apple firmware that a
user supplies/downloads is not licensed or distributed by this project. This
is an experimental community project, not an Apple product or a replacement
for testing an app on its supported physical hardware.
