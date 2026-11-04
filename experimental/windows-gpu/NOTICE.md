# Source and licensing notice

The repository's MIT license does not relicense third-party code represented by these patches.

- The Reims patch modifies tqmane/reims-vgpu at the exact public revision in `sources.json`. Its existing attribution and `GPL-2.0-or-later OR LGPL-3.0-or-later` licensing apply to those modifications.
- The metal2vulkan patch and the synthetic LLVM test fixture use the corresponding project's `GPL-2.0-or-later OR LGPL-3.0-or-later` terms. The RGB test kernels are authored synthetic probes, not captures of a consumer's shaders.
- QEMU changes retain the source files' GPL-2.0-or-later notices. The Windows RAM bridge also records the tqmane QEMU reference revision in the manifest.
- Full GPL-2.0, LGPL-3.0 and GPL-3.0 texts are in `LICENSES/`. LGPL-3.0 incorporates GPL-3.0. Consult the fetched projects for file-specific notices.
- The independent ASTC reference and Arm astcenc Rust dependencies are downloaded from their public sources; they are not vendored or relicensed here.

The preparation/build/launch wrappers are authored for this repository. There are no Apple firmware, guest disks, extracted GPU driver binaries, captured consumer shaders, private signing keys or credentials in this package. Users supply their own prepared device bundle locally. Only source patches, synthetic textual fixtures, metadata and documentation are committed.
