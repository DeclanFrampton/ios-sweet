# iOS Sweet — Windows GPU progress and engineering handoff

Prepared for the shared iOS Sweet workspace on 4 November 2026. Evidence refreshed at approximately 22:00 UTC. This is an engineering handoff, not a claim that the iPhone is finished or stable.

## Later milestone and source publication

The repaired GPU instance subsequently reached the visible **Get Started** screen. Before the user pressed it, a new paused-device checkpoint was captured at `E:/ios-sweet-checkpoints/20261104-get-started-phase`; all 13 device files passed checksum verification and the same instance resumed. This supersedes the earlier welcome-only visual observation below. It does not prove home-screen/app acceptance or exact-step cold restoration.

The source work is now exported as pinned, reconstructable patches and portable development wrappers under [experimental/windows-gpu](experimental/windows-gpu/README.md). Fresh public-source preparation, patch application and reconstructed file hashes passed; the owned textual fixtures compiled locally. Four plan-only launcher/manifest tests, the existing viewer-poll test and seven C poll-limit assertions passed. Full fresh-machine QEMU/renderer rebuilding remains unverified for the new wrappers.

The [shared Notion handoff](https://app.notion.com/p/40ec84878c9681e3b14bf386550bde59) is published beneath iOS Sweet Studio. GitHub access to Dan's repository is read-only, so the contribution uses `DeclanFrampton/ios-sweet`, with a dedicated `feature/gpu-development` base. Dan's remote had no GPU development branch at publication time; review in the fork is separate from an upstream merge.

## What has changed

We now have a real iOS guest rendering through the RTX 4070 Ti on native Windows. It has reached interactive setup, including language/country selection, appearance and Camera Control. This is beyond the earlier synthetic framebuffer demonstrations. The latest work fixes a specific host-renderer abort encountered after Camera Control Continue; focused GPU tests and the native build passed, and the repaired instance reached the welcome screen. The Camera Control transition still needs a live retry.

There are two distinct tracks in this repository. The original iOS 16/SWEET work concerns the Redmi Note 10 Pro/SM7150 and an older CPU-rendered guest. The current Windows GPU experiment uses a separate iPhone17,3 iOS 26.6.2 (23G90) virtual-device bundle, prepared with a matching cloudOS paravirtual GPU driver. Success here does not prove native iOS GPU support on the Redmi hardware. The original disks and backups have been preserved.

The CPU still runs under QEMU TCG. Dynarmic work demonstrated small synthetic ARM64/GPU-memory primitives; it is not a replacement iOS machine, and we have not eliminated QEMU.

## Current status and evidence boundary

| Area | Verified | Still unresolved or unverified |
| --- | --- | --- |
| GPU path | Real iOS boot/setup frames through Reims/metal2vulkan and RTX 4070 Ti; authored GPU regression readbacks | Stable visual correctness across iOS/apps and Apple-hardware precision parity |
| Input | User progressed through setup; prior trace recorded 5,184 outgoing pointer reports and 4,893 guest-consumed USB reports | Consistently responsive dragging through remote desktop; variable UI transition delays |
| Latest crash | Matching Windows dump identifies a surplus mipmap scratch-buffer destructor entering the Vulkan accessor outside the exit guard | Camera Control Continue after the deployed fix has not been replayed live |
| Latest fix | Narrow lifetime guards added to mipmap and GPU-pool surplus cleanup; three focused tests passed; optimized native build passed | Full suite, long-running stability and completed setup not proven |
| Recovery | Two verified device-file checkpoints; one cold restore reached welcome; pause/copy/resume checkpoint retained the live instance | No RAM/GPU migration; exact setup phase after a cold restore is not proven |
| Performance | Measured CPU validation bottleneck improved; optimized ASTC fixture decode improved; GPU legs often a few milliseconds | No sustained end-to-end FPS or startup-time guarantee |

At the latest read-only check, `handler-guard-boot-receipt.json` reported running and actual QEMU process 34608 existed. Its latest log had no fatal/panic/exit-guard-abort message, but the latest frame-submission gap was around 38 minutes. That could include an idle or sleeping display; process existence is not responsiveness proof. The most recent visual check was the welcome screen after the repaired boot. Refresh process, log and screen before operating it. This handoff did not restart or change that instance.

## Architecture and configuration

The experimental path is native Windows QEMU vphone → guest paravirtual GPU driver → Reims vGPU → metal2vulkan → Vulkan → NVIDIA GPU. Some unsupported texture compression is decoded on the CPU before GPU upload/sampling. It is not native NVIDIA ASTC support.

- Host: Ryzen 5 5600X, 6 cores/12 threads, 32 GiB RAM, RTX 4070 Ti with 12 GiB VRAM.
- Guest: 4 GiB RAM, 4 vCPUs, ARM64e execution through TCG.
- TCG translation cache: 2,048 MiB, increased from 512 MiB with a host-memory guard.
- Guest page geometry: fixed 16 KiB in the experimental renderer build.
- Display: 860 × 1864 physical pixels at 2× scale, giving 430 × 932 logical points. Earlier physical/logical-scale mismatch made controls oversized. Compared with 1290 × 2796 at 3×, the current mode has 2.25× fewer pixels.
- Renderer: `ios-perf` Rust profile, optimization level 2, line-table symbols, overflow/debug checks retained; ASTC codec optimization level 3.
- GPU decoded texture storage can be private/device-local. VRAM is not general-purpose guest RAM and does not remove ARM CPU translation costs.
- QMP: loopback 19688; VUSB: loopback 19690. These are local control endpoints, not public services.

Initial reference pins recorded in local notes: Reims `8f316b5f21908ddeb1e454ce50356ed6e1d2f6cf`; metal2vulkan `7f09d6be92aa98fb8f5cf4d47c8441d2351bc6fb`. The running build includes substantial local patches. These pins alone do not reproduce it; preserve the source snapshots and build manifests.

## Bring-up and fixes already completed

### Native platform, restore and shader loading

- Ported the vphone QEMU path to Windows with section-backed RAM and the 16 KiB Reims configuration.
- Kept the Windows GPU guest isolated from the original SWEET device and unrelated WSL/Docker workloads.
- Corrected USB/IP unlink handling and restore timing. A successful isolated restore ended with `Status: Restore Finished`, exit 0; system volume sealing and a separate backup comparison passed.
- Enabling TCP `nodelay` raised the observed restore transfer from about 1.45 to 11.07 MiB/s in the relevant attempts. This is restore transport evidence, not boot/render FPS.
- Enabled process isolation for the guest's 256 GiB virtual-address request. That address-space reservation is not 256 GiB of committed physical RAM.
- Fixed parsing of an omitted optional shader-container header. Eighteen container tests passed; later real iOS frames were rendered.
- Earlier small Windows worker stacks caused crashes. The established compile-worker stack change uses an 8 MiB reserve with lazy commitment; it is not a blanket claim about every runtime thread's stack.

### Render formats and visual correctness

- Added bounded RGB8_444_2P/raw 542 support using G and BR planes and a float render shadow. Actual GPU readback tests covered reads, clear/store, source-over blending, load preservation and padding at 7×3, 1×1 and 8×2. Other unsupported actions, resolves/options and partial-mask cases remain guarded. Apple hardware equivalence has not been established for this private format.
- Extended ordered premultiplied source-over framebuffer-fetch support to RGBA16Float, without clamping floating-point source values. Two direct tests passed. The fixture compile/link test was skipped when llvm-as was unavailable, so it must not be counted as end-to-end coverage.
- Implemented a write-only RGB9E5 fallback through a compatible R32_UINT texture view. The GPU shader clamps and packs shared-exponent fields, including exponent carry. It keeps native storage preferred where supported and rejects unsupported read/atomic/non-float forms. Apple-specific rounding is unqualified and a `DeviceTexelConversion` precision notice is retained.
- The RGB9E5 regression ran on the RTX: 381 pixels in shared storage and 381 in private storage, including HDR, NaN/Inf, exponent boundaries, masked preservation, sampled values and padded raw readback. Both passed. Translator semantics version 1695 invalidates older artifacts.

### ASTC textures

The early nil-allocation workaround did not solve ASTC: it caused missing-texture faults. It was superseded by real decoding and ordered transfers. Do not re-enable it as a fix.

- Arm astcenc 5.3.0 via pinned astcenc-rs/astcenc-sys 0.2 decodes the observed 4×4 LDR and 6×6 sRGB formats into fp16/RGBA16F sampled backing.
- Original compressed blocks are retained separately; guest format identity is preserved. For sRGB, RGB is linearized while alpha remains linear.
- Supported shape is bounded: sampled 2D, dimensions up to 4096, valid mip ranges, shared/private storage, one layer/sample. Unsupported shapes and operations still refuse explicitly.
- GPU-produced buffer uploads are ordered through GPU readback, deferred CPU decode and upload before later consumers. Private multi-mip uploads use parent-relative one-level views and separate per-mip compressed stores.
- Texture-to-buffer reads return retained original compressed bytes, not decoded RGBA bytes mislabeled as ASTC. Ordered host-produced row uploads preserve producer order and padding.
- The final seven focused ASTC tests passed in about 0.75 seconds, including public reference images, colour/alpha, padded and partial uploads, private mip views, producer/decode/consumer ordering and ordered compressed readback. This is focused coverage, not the full suite or all ASTC formats.

## Latest Camera Control crash and repair

The two recent exits were Windows aborts, not another unsupported-format diagnosis. The latest restored run lasted about 4,713 seconds and logged at 4,708.067 seconds:

```text
metal2vulkan: the runtime's thread metal2vulkan-handlers reached the device outside an exit-guard section
```

The matching Windows minidump resolves the fault chain:

```text
exit_guard::check
DeviceShared::vk
mipmap_scratch::Lease::drop (surplus block release)
CommandBufferShared::complete (retained-resource cleanup)
contexts handler thread
```

The destructor evaluated the checked Vulkan device accessor before the release helper entered its guard. The repair adds a narrow `exit_guard::enter()` before that accessor in the surplus-release branch. The same defect was fixed in `gpu_pools::PoolLease::drop`. It does not disable the guard or put arbitrary user callbacks inside a lifetime section. If process shutdown refuses a new section, raw resources are left for process termination, following the existing guard policy.

Three focused checks passed in 1.51 seconds: scratch return in both size orders retains the largest spare; surplus index/mesh pool return works on runtime threads without an outer guard; existing guarded scheduler-write checks pass. The optimized native build passed in 6m25s. The matching DLL/PDB pair was deployed and the new instance reached visible welcome. Camera Control Continue is still unverified on this build.

The earlier dark-appearance failure was different: `variable_blur_frag_lph`, Format/NotImplemented at block 0/instruction 0. Diagnostic construction-site and lowering-input tracing were added. Its exact unsupported operation and a functional resolution were not established. Do not call the Camera Control cleanup fix proof that the blur failure is solved.

## Performance, memory and input lessons

- GPU completion/presentation is frequently around 2–3 ms while CPU/preparation gaps can be seconds. Short welcome-screen submission samples reached roughly 57–68/s, but this does not establish sustained displayed FPS.
- Windows VirtualQuery validation was a measured CPU bottleneck. Source spans are now validated in ascending address order with reuse of queried extents only within the operation. Logical protection checks remain; there is no cross-call permission cache.
- Ten focused memory/alias/ASTC tests passed at that stage. In logged slow ExecIndirect3 calls (only calls ≥5 ms) during 90–200-second boot windows, conditional median fell about 180 → 44 ms, p95 691 → 100 ms and max 2133 → 215 ms. Different boot progression and the logging threshold limit comparisons; do not turn these into phone-FPS claims.
- Optimizing the renderer/codec cut selected 256×256 ASTC fixture decoding about 65 → 5.7 ms. These are fixture timings, not UI FPS.
- The viewer intentionally discarded the first focus click. An opt-in direct-touch focus-click path, keep-on-top/raise and pointer/USB traces were added; 19 pure input tests passed. Live user input transport was later observed. This does not prove every drag is responsive.
- A QMP timeout was caused by a leaked `socket.makefile()` stream in the boot monitor, not proven guest deadlock. Closing the stream and socket restored independent status queries of about 6–8 ms. Windows poll-cap experimentation remains disabled (`VPHONE_WIN32_POLL_MAX_MS=0`); do not credit it with fixing input.
- An idle Windows `g_poll` stack and a long no-frame interval alone do not prove a deadlock.
- Prior notes record a requested C: pagefile configuration of 40,968 MiB initial/65,536 MiB maximum; effective application was not verified and no host reboot was performed. A research WSL swap file was temporary. Neither is evidence that VRAM became RAM or that memory pressure is solved.

## Recovery checkpoints and current local layout

All paths below are local to Declan's machine, not Notion-hosted artifacts. No Apple firmware, disks, extracted proprietary shaders, credentials or crash-dump payloads are uploaded with this handoff.

| Location | Purpose |
| --- | --- |
| `D:/ios-sweet/NOTES.md` | Authoritative dated engineering log; latest entries supersede earlier hypotheses |
| `D:/ios-sweet/.studio/experiments/gpu-path-audit-20261103` | Audit root: source snapshots, test/build logs, deployment hashes and launchers |
| `.../reims-windows-16k` | Patched native renderer tree |
| `.../metal2vulkan-ios-container` | Patched translator/runtime tree |
| `.../qemu-vphone-windows` | Windows QEMU source tree |
| `C:/Users/decla/Documents/Codex/2026-11-03/clone-this-for-me-on-a/native-vphone-build/qemu-system-aarch64.exe` | Native QEMU executable |
| `E:/ios-sweet-working/restored-20261104-1930` | Current writable GPU device bundle |
| `E:/ios-sweet-checkpoints/20261104-1918-device-state` | Verified stopped-file recovery backup taken after an exit |
| `E:/ios-sweet-checkpoints/20261104-quickstart-phase` | Newer verified paused-file checkpoint at Quickly Set Up iPhone |

Each checkpoint contains 13 root device files, including the 64 GiB disk, NVRAM, SEP storage, identity/configuration and a matching renderer pair. SHA-256 comparison passed. The first checkpoint was cold-restored into a new working copy and reached welcome. The newer checkpoint used QMP pause, host block-I/O drain/flush, file copying and same-instance resume; checksum verification passed afterward. Guest filesystem caches were not frozen. No CPU RAM/GPU state was saved. Returning to exactly the same setup step after a cold restore remains untested.

Never boot directly from a checkpoint or overwrite it. Restore into a new writable bundle, verify file hashes and use the matching renderer/native build. Preserve the latest working state until a rollback is explicitly chosen. No automatic reboot loops, host reboot or global WSL restart.

Current evidence files in the audit root:

- `handler-guard-boot.py`, `handler-guard-boot-receipt.json`, `handler-guard-launch.log` and working bundle `.runs-native/handler-guard-serial.log`.
- `handler-guard-tests.log`, `handler-guard-native-build.log`, `handler-guard-deploy.json`, `handler-guard-source-snapshot/`.
- `camera-control-guard-crash-stack.txt`; matching previous DLL/PDB in `before-handler-guard-symbols/`.
- `astc-readback-tests.log`, `astc-readback-source-snapshot/`, `rgb9e5-gpu-test.log`, `rgb9e5-source-snapshot/`, `focus-touch-source-snapshot/` and the corresponding earlier build/deploy logs.
- `checkpoint-quickstart-20261104.py` and log; `checkpoint-restore-20261104.json` and restore logs.

Current deployed renderer DLL SHA-256: `9EE7191A0B8DC9D1530E5B47C8092D205A2AA052BCE82C541A0966D2B2EEAEB8`. Matching PDB: `E44F511750EDEB37FCCF0267CE8572036ADF2772F2DB7451034C68FEA8738396`. Refresh these before a later deployment; never debug an old dump with a mismatching PDB. `LLDB_USE_NATIVE_PDB_READER=1` was necessary for correct project symbols.

## Repository state and next work

Repository: [danhol86/ios-sweet](https://github.com/danhol86/ios-sweet). Local branch `perf/ios-viewer-refresh`, current local HEAD `cea34a1335347a1b1fdecfba442d8c05345c5dae`. Push/remote availability was not verified for this handoff. Main-repository milestone commits document results in NOTES; much of the actual experimental renderer/QEMU work remains ignored under `.studio`. Do not assume cloning remote main reproduces the current GPU build. Packaging/reviewing those local patches is outstanding.

Immediate follow-up, with no owner or deadline assigned here:

1. Refresh the current log and screen, then replay Camera Control Continue on the handler-guard build. Confirm survival and the following screen; capture matching-symbol evidence if it fails.
2. Resolve the independent blur-shader refusal if it recurs. Diagnose its actual lowering input rather than guessing ASTC or bypassing guards.
3. Finish setup and record sustained input, visual correctness and frame timings. Treat a visible screen, pointer transport and usable application behaviour as separate gates.
4. Test recovery into a disposable working copy and document which setup steps really persist. Full live GPU/RAM migration is separate engineering work.
5. Measure cold/warm startup and CPU submission gaps with comparable workloads. Remaining CPU translation/validation costs need evidence before another optimization.
6. Preserve and package the authored local patches, pinned sources, commands and manifests without redistributing Apple artifacts. Review warnings and run broader relevant checks before production claims.

Public reference material used during the work includes [vphone-linux](https://github.com/YahiaAngelo/vphone-linux), [Reims](https://github.com/tqmane/reims-vgpu), [metal2vulkan](https://github.com/tqmane/metal2vulkan), [Arm ASTC codec](https://github.com/ARM-software/astc-encoder), [Vulkan format rules](https://docs.vulkan.org/spec/latest/chapters/formats.html), and [QEMU disk/snapshot documentation](https://qemu-project.gitlab.io/qemu/system/images.html). Local measurements and tests, not those external projects' performance, support the results above.

## 2026-11-04: completed setup and resident-page validation experiment

User photos show SpringBoard and Settings. Verified13paused device-file copies at E:/ios-sweet-checkpoints/20261104-springboard-complete; same VM resumed. No RAM/GPU migration or exact-screen recovery claim. Prior Get Started checkpoint remains untouched.

Published fork draft PR https://github.com/DeclanFrampton/ios-sweet/pull/1 from feature/windows-native-ios-gpu into feature/gpu-development. This is a fork review branch because upstream has no GPU branch and no push permission. Head before this follow-up eeaa1f4; no CI checks reported. Shared Notion handoff https://app.notion.com/p/40ec84878c9681e3b14bf386550bde59 updated with SpringBoard and performance investigation.

User reports apparently frozen clock. Guest still produces intermittent frames and serial work, so distinguish stalls/static lock screen from dead process. Logs show VirtualQuery-based checks taking70-80ms. Read-only20confirmed-resident-address comparison: VirtualQueryEx median56.0531ms max128.5143 versus QueryWorkingSetEx median0.0050ms max0.0683; all20pages still valid. First probe used nonresident low RAM pages and is not resident-fast-path proof. Random1024-page sample was808resident, not universal residency. No end-to-end FPS speedup claim.

Implemented bounded4096-page K32QueryWorkingSetEx fast path with logical permissions, all requested pages checked, no cross-call cache, and existing VirtualQuery fallback for invalid/nonresident/guard/unknown results. Four real/modeled validation tests passed, including interior noaccess/guard without consuming guard, protection restoration and unmap. Seven ASTC regressions passed1.38s. Native optimized build resident-pages-build.log/.err currently pending; old VM34608 exited0 after QMPquit. Do not relaunch before build/deploy succeeds.

Added user-operated PhoneControls.cs / phone-controls.ps1 and iPhone controls desktop shortcut. Home sends the viewer middle-click shortcut (guest Cmd+H); separate slower swipe unlock control accounts for letterboxing. Geometry/native INPUT layout self-test and PowerShell parse passed; actual Home-to-SpringBoard acceptance remains pending. Normal exported launcher disables verbose input/FIFO diagnostics with --diagnostics opt-in; four plan tests passed. New27-file public-base Reims reconstruction/hash check passed. Keep Apple artifacts/private checkpoints out of Git. Quiet retry script resident-pages-boot.py is prepared against the same completed-setup working bundle, with warning logs and per-second frame counts only.

Native optimized build passed in2m46s. Six Windows VM tests and seven ASTC GPU regressions passed. Deployment initially stopped because the Windows PowerShell child could not load Get-FileHash; before any boot, verified original DLL backup/PDB hashes, completed matching DLL/PDB backup, then deployed/verified via Python SHA256. Deployed DLL D1E3555B4EA6041C4294216E50F052D4AC83F5E4AE2318A7F5144AFAAB9FD97A. One quiet resident-pages boot launched; actual QEMU48692, monitor70248, wrapper52672 (refresh IDs). Loaded module path verified. Same working disk, no reset; live responsiveness/Home acceptance pending.

Live resident-pages retry reached lock screen at~130s. Clickable Swipe up/unlock returned to SpringBoard; Settings cold launch rendered after roughly45s. Clickable Home/SpringBoard then returned from Settings to Home, visually verified through CUA. Instance remains running, no fatal seen. Short samples ranged0-61submissions/s and do not establish sustained FPS or unique frames. Cold app latency is still poor; reduce guest motion/transparency next. Commits a3c1906 and ffee43e pushed to fork draftPR1; no CI checks reported.

Follow-up: consumed touch traces and hid_pointer_sync source show the first absolute button-down coordinate can be overwritten by subsequent same-button motion before the guest polls. Preserved absolute button-edge reports until consumed, while retaining later motion compression and unchanged relative-mouse behavior. Regression replays down/move/move/up at16ring positions plus6predicate cases; compiled/ran with -Wall -Wextra -Werror. Actual HID object and native QEMU link passed. Old executable preserved as qemu-before-input-anchor.exe. Clean prior VM exit0; one input-anchor boot now running (actual QEMU31176, monitor12220, wrapper34772; refresh IDs), same working disk and resident-page renderer. Exported17-file QEMU patch reconstructs pinned public base/hashes. Live fast-drag acceptance pending; no animation preference actually changed yet.

Latest live check: input-anchor boot31176 remains running and CUA shows General in Settings at~260s. Quick CUA drag did not reliably establish unlock; queue regression proves edge coordinates are retained, not complete guest gesture timing. Slower unlock/Home controls were verified on resident-pages boot; current viewer is visibly advancing through Settings. No sustained smoothness claim: renderer submission samples vary0-68/s and app transitions still pause tens of seconds. Reduce Motion/Reduce Transparency were not changed; do not claim guest preferences applied. Leave this instance running, no further reboot loop. Next: profile remaining guest/background/command stalls with a fixed workload and record all-call timings plus gesture-to-frame latency. Completed-setup backup remains verified and unchanged. Input fix14f29e4 is pushed to fork draftPR1.

2026-11-05 idle freeze: preserved same live31176 before restart. MiniDump capture-freeze-before-20261105.dmp/stacks shows mainloop g_poll and4APs waiting at capture, UI thread waiting for messages; QMPstatus responded0.4ms. Live trace capture-input-live-20261105.log proves correct ABS press/move/release reachesQEMU, USBtouch slot3/ep3 reports complete20bytes, keyboardslot1 reports complete8bytes. CtrlAltHome CUA did not release; CtrlAltSuper visibly clearedcapturetitle, but unlock still failed. SameVM QMPstop/cont confirmedpaused/running and did not restoreunlock. Not proven host-input swallowing orGPUspin. Currenttrialprepares explicit --idle-input-workaround: capWindowswait16ms and optoutWindows systemkeyboardgrab forabsolute input; relativegrabunchanged. Tests/build pending, no datareset/hostreboot.

Idle-input trial: 110window/input tests passed,2ignored, including no-grab policy;7poll-limit assertions and4launcher tests passed. Real CLI --idle-input-workaround plan check passed without booting. Reconstructed27Reims files/hashes. Native build passed1m09s; DLL/PDBpair verifieddeployed(43E62AC809946E76816FE96F3A12625B70184632976C9C67BF8DE959C2298178 DLL), oldpairbefore-idle-input-symbols. OldVM31176quitcleanly; one freshboot ofsameEworkingbundle, actualQEMU64596/monitor48548/wrapper61384 (refresh IDs). Runtime log confirms16mspollcap. CUAverifiedSpringBoardaftercontrollerunlock, withoutreleasechord, around177s. Nowtestingidle/lock/unlock; notprooflongtermfix. No AutoLock/security/guestsettings changed.

2026-11-05 Safari: user confirms Auto-Lock set toNever. New screenshot banner says web page reloaded because a problem occurred; classify as page-process termination/reload, not an ordinary DNS error. Host direct HTTP/HTTPS example.com both200; guest NAT metadata shows established TCP443 and UDP443 traffic. Running4GiB QEMU remainedalive; no matching hostfatal/panic/WebKit/jetSam cause in serial logs. Google.com is user reproduction target. Current target crash reports unavailable: prior iOS-GPU-Research WSL distro root lookup fails74 afterhostrestart; workingUbuntu lacksdiagnostictools/USBIP. No globalWSL reset/kernelchange orphysicaldeviceaccess attempted. Preserved4GiB safari-network logs; cleanQMPquit then one same-disk8GiB trial safari-8g-boot.py, same4CPU/2GiB TCGcache/GPU/resolution/no-grab16msprofile. This testsmemorypressurehypothesis only; cause andSafariacceptance unverified. No cache/site-data deletion, certificate bypass orSafari feature changes. LocalNATprobe onlyhost-self-tested; guestUItest wasstoppedbyEscape inpriorinteraction, probe ended/stopped.
