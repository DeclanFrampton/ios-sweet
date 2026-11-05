# Experimental native Windows iOS GPU development

This source-only development package preserves the local GPU work described in [the handoff](../../IOS-GPU-HANDOFF-2026-11-04.md). It does not change `start.cmd`, replace Studio's default backend, supply Apple firmware, or claim a stable usable iPhone. The original iOS16/SWEET baseline and this separate iOS26/vphone GPU experiment are different tracks.

## What is included

`sources.json` pins public Reims, metal2vulkan, QEMU-vphone and independent ASTC reference revisions. Three patches reconstruct the locally tested source changes, including 16KiB mapping, Windows integration, ASTC uploads/mips/readback, RGB render formats, input focus, memory validation and the scratch-lease exit-guard fix. Source hashes record LF-normalized reconstructed files. Owned synthetic LLVM fixtures are supplied as text and compiled locally; no guest shaders or binary images are distributed.

The Reims patch includes the two locally committed guest-page/IOSurface changes as well as the later uncommitted fixes. It applies directly to the public base, not to a private local commit. Patches preserve third-party attribution; the fetched projects' GPL/LGPL licensing continues to apply. The QEMU Windows bridge derives from the source and reference revisions identified in the manifest and historical handoff.

## Prepare sources

Prerequisites: Git, Python 3.11+, Rust MSVC toolchain `1.98.1`, x64 Visual Studio Build Tools/Windows SDK, LLVM clang/libclang, CMake, an installed Vulkan driver, and MSYS2 UCRT64 tools/development dependencies for QEMU (GCC, Ninja, pkg-config, GLib, pixman, slirp, nettle, libtasn1, PNG, zlib and lzfse as required by configure). This package does not install or upgrade host tools. Keep heavy build concurrency low.

From the repository root:

```powershell
python experimental/windows-gpu/prepare_sources.py .studio/windows-gpu-sources --qemu-submodules --clang C:/path/to/LLVM/bin/clang.exe
```

Use a new destination. The script refuses existing source directories and does not overwrite them. It fetches public pinned commits, checks and applies patches, verifies reconstructed source hashes, and builds only the owned test bitcode. `--skip-fixtures` prepares source without those examples; run the fixture compilation before example tests.

In an x64 Visual Studio Developer PowerShell, set `LIBCLANG_PATH`/LLVM PATH if the codec build requires it, then:

```powershell
./experimental/windows-gpu/build_renderer.ps1 -SourceRoot .studio/windows-gpu-sources
```

The DLL, matching PDB, GCC-compatible MSVC import library, public header, pkg-config file and hashes go to the source root's `reims-win-dist`. Existing deployed output is refused rather than overwritten. `CARGO_TARGET_DIR` must be unset or use the normal workspace target directory for this staging script.

For QEMU use an MSYS2 UCRT64 shell with its toolchain on PATH. Use an NTFS build directory with reliable timestamp precision; the local D: source volume caused a Meson timestamp-rounding problem, so the successful local build output was on C:. For example, adapting paths:

```bash
bash experimental/windows-gpu/configure_qemu.sh /d/repo/.studio/windows-gpu-sources /c/gpu-qemu-build
cd /c/gpu-qemu-build
ninja -j1
```

No full fresh-machine rebuild is claimed for these portable wrapper scripts. Exact local sources/builds passed before export; patch applicability and source reconstruction are separately checked. Read configure's dependency errors rather than guessing a successful build.

## Test and launch

The following commands mirror the focused local regressions. Run from the relevant fetched workspace, not the parent ios-sweet Cargo workspace:

```powershell
# metal2vulkan-ios-container: actual GPU allocation/destruction regression
$env:RUSTFLAGS='--cfg m2v_gpu'
cargo +1.98.1-x86_64-pc-windows-msvc test -p metal2vulkan-runtime --lib handler_guard_tests -- --nocapture --test-threads=1
Remove-Item Env:RUSTFLAGS
cargo +1.98.1-x86_64-pc-windows-msvc run -p metal2vulkan-runtime --example rgb9e5_storage
cargo +1.98.1-x86_64-pc-windows-msvc run -p metal2vulkan-runtime --example rgb444_surface

# reims-windows-16k
cargo +1.98.1-x86_64-pc-windows-msvc test --profile ios-perf -p reims-vgpu-vulkan --lib astc_ -- --nocapture
```

`launch.py` prints a paused launch plan by default. It needs your own separately prepared compatible working bundle and built native QEMU; it does not prepare firmware. Configure process-local paths:

```powershell
$env:IOS_GPU_SOURCE_ROOT=(Resolve-Path .studio/windows-gpu-sources).Path
$env:IOS_GPU_QEMU='C:/gpu-qemu-build/qemu-system-aarch64.exe'
$env:IOS_GPU_UCRT_BIN='C:/msys64/ucrt64/bin'
python experimental/windows-gpu/launch.py E:/your-disposable-working-bundle --memory 4G --cores 4 --qmp-port 19688 --vusb-port 19690
```

Add `--run` only when ready to open that bundle writable. It starts paused; `cont` through a local QMP client is separate. Set `REIMS_EXPERIMENT_ASTC_CPU=1` for the implemented ASTC fallback. The current local boot also uses `REIMS_VGPU_WINDOW_ON_TOP=1` and `REIMS_VGPU_FORWARD_FOCUS_CLICK=1`; input traces are optional. Keep `VPHONE_WIN32_POLL_MAX_MS=0`. Do not use the obsolete nil-ASTC workaround.

Never run two instances against one bundle. The machine uses multiple views of the same disk/NVRAM with file locking off, so independent overlays for those aliases are not interchangeable. Keep original disks/checkpoints untouched and launch a separate working copy. QMP/VUSB bind loopback. There is no live GPU/RAM snapshot support. Do not use `savevm` success/listing as evidence of usable restoration.

## Validation and remaining work

### Idle input recovery trial

`--idle-input-workaround` selects an experimental Windows touch profile: a16ms main-loop poll cap and `REIMS_VGPU_WINDOW_KEYBOARD_GRAB=0`. The latter leaves Windows system shortcuts ungrabbed for absolute input; relative-pointer capture retains its required grab. Keyboard focus, button/key release on focus loss and guest input routing remain active. The standard launch profile is unchanged. [SDL documents system-shortcut interception as the purpose of keyboard grabbing](https://wiki.libsdl.org/SDL3/SDL_SetWindowKeyboardGrab).

This trial follows a long-running lock-screen failure where QMP responded immediately, touch/keyboard reports completed through USB, and a stalled-state dump showed the main loop and application CPUs waiting. Releasing capture or pausing/resuming did not reliably unlock it. Those observations do not prove a GPU deadlock or identify a guest root cause. The profile is defensive mitigation under evaluation; a fresh boot alone is not proof of idle recovery. Validation and live limits are recorded in the handoff.

### Completed setup follow-up

The user reached SpringBoard and opened Settings on the Windows GPU instance. This is post-setup interaction evidence, not sustained smoothness or broad app compatibility. A verified paused-device-file checkpoint preserves completed setup locally; it contains no GPU/RAM state.

Run `phone-controls.ps1` to open the user-operated **Home / SpringBoard** and **Swipe up / unlock** companion. It compiles the included C# source using the Windows .NET Framework compiler and keeps its executable under local app data. Home uses the viewer's middle-click-to-Cmd+H path; swipe uses aspect-fitted client coordinates. It refuses missing, minimized or ambiguous viewers and stops a swipe if focus changes. Keep the viewer at its normal guest aspect fit. No QMP input is used. Closing this companion leaves the VM running.

Normal `launch.py` runs disable pointer/report/FIFO tracing and retain warnings; `--diagnostics` opts back in. The required ASTC CPU fallback is enabled by default. This removes unnecessary diagnostics; no standalone FPS benefit has been measured.

The Windows memory check now first queries all requested resident pages with `K32QueryWorkingSetEx`, bounded to4096unique pages, without caching between operations or reading guest bytes. Logical protections still apply. Invalid/nonresident/guarded/uncertain results fall back to the existing `VirtualQuery` validation. A read-only20-address experiment on confirmed resident pages in the running VM found median56.05ms for `VirtualQueryEx` versus0.0050ms for the page query (20/20pages still valid); this isolates metadata cost and is not a phone benchmark. Real protection/guard/unmap regression checks and native deployment results are recorded in the handoff.

Public basis: [Microsoft page query](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-queryworkingsetex), [validity/protection fields](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-psapi_working_set_ex_block), and [vphone performance findings](https://github.com/YahiaAngelo/vphone-linux/blob/main/docs/PERFORMANCE.md). The existing16KiB target pages, TLB options and2GiB translation cache already follow that fork's recommendations. CPU execution remains TCG, so GPU support alone cannot remove serial app-launch or guest-service delays.

Local evidence: the latest GPU lease cleanup tests passed (including real mip scratch and index/mesh pool returns on unguarded runtime threads); optimized renderer build passed; real iOS welcome/setup rendered on RTX4070Ti. Camera Control after the final fix, stable apps, sustained FPS, exact-step snapshot restore and fresh-PC reproducibility remain open. The earlier independent blur-shader refusal is not established as resolved. Full upstream suites have not been run; no merge acceptance is implied.

`tests/test_launch.py` uses disposable fake files, checks plan arguments and refusal paths, and never boots a guest. Historical local result counts and limitations are in the handoff. The running native device and all private evidence remain outside Git.

The QEMU patch also preserves absolute button-edge coordinates until consumed: a delayed guest must see the original finger-down position before coalesced movement. Relative mouse compression is unchanged. tests/test_hid_pointer.c replays a drag at all16ring offsets and checks six compression cases against the production predicate; the real HID object and native executable also compile. This addresses lost gesture starts, not guest frame scheduling. Live acceptance results are in the handoff.
