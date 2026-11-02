# iOS Sweet Studio

A native Windows desktop workspace for an experimental, locally emulated
**iPhone running iOS 16.7.16**: embedded iPhone viewer, IPA file selection,
local development signing, installation, app library and launch controls.

> **Clone and run. No Studio installer.** Everything is on
> [`main`](https://github.com/danhol86/ios-sweet/tree/main), the default branch.
> Run one command after cloning: **`.\start.cmd`**. It downloads/verifies its
> private runtime dependencies and opens the app directly from this source.

## Quick start — one command after cloning

```powershell
git clone https://github.com/danhol86/ios-sweet.git
cd ios-sweet
.\start.cmd
```

That is the normal user setup. **Do not follow the compiler/SDK build guide
below just to run the app.** No separately installed Python, Docker, WSL,
Apple SDK, Node, compiler, GitHub login or signing certificate is needed.

The command downloads a pinned, SHA-256-verified dependency ZIP into `.studio/`,
checks Microsoft WebView2 (installs that dependency from Microsoft only if
missing), then opens the **Studio code from your clone**. It does not use a
Studio setup EXE, change your system Python/PATH, or register an installed app.
Run the same command next time: verified downloads are reused.

Already have an iPhone running from another clone or data folder? Use
**Connect to running iPhone** when Studio offers it. The existing device and
installed apps are reused without a restart or another firmware download;
see [reconnecting an existing device](docs/RUN_FROM_SOURCE.md#a-fresh-clone-says-the-iphone-is-already-running).

On first use, confirm the in-app firmware authorisation and select
**Download & create iPhone**. Apple firmware is downloaded directly from
Apple, not bundled in GitHub. Then choose an IPA and click **Install & launch**.
Your private device and apps live in `.studio/data/`; keep that folder when
updating with `git pull`.

If an already prepared device fails on **Start iPhone** in `mkadt.py`, update
with `git pull --ff-only`, close Studio and run `start.cmd`, then press
**Start iPhone again**. The missing private product device tree is now fetched
and verified automatically; **do not create the disk again**. Runtime r3
includes its native decoder, not Apple firmware. See
[boot-file troubleshooting](docs/RUN_FROM_SOURCE.md#mkadtpy-fails-when-starting-an-already-prepared-iphone).

**Requirements:** Windows 10/11 x64 (Intel/AMD, Windows build 19041+), internet
for initial downloads, 35 GB free storage for device creation, and 6 GiB free
RAM before starting the emulated iPhone. The desktop bootstrap does not itself
start QEMU. The emulator remains experimental and not every IPA is supported.

If device creation fails shortly after starting with
**`STUDIO_PREPARER_FAILED`**, update the source and retry; a compressed-DMG
transport bug is fixed on `main`. Keep your downloaded firmware and private
device data. See [the failure and recovery notes](docs/RUN_FROM_SOURCE.md#setup-fails-after-a-few-seconds-with-studio_preparer_failed).

See [run-from-source help](docs/RUN_FROM_SOURCE.md) for another data drive,
logs and troubleshooting. For dependency checks without opening a window:

```powershell
.\start.cmd -PrepareOnly
```

## Preparation progress and logs

If setup appears stuck at **Preparing your private iOS disk**, update with
`git pull --ff-only` and reopen using `.\start.cmd`. Runtime **r2** repairs a
missing QEMU boot ROM that prevented the original source runtime from booting
its preparation engine. The next launch downloads/verifies the repaired
runtime without deleting your firmware cache or private iPhone data.

Use **Setup log** in the top bar for timestamped live output, the current
step, elapsed time, last output time, process CPU/I/O activity, file-copy
progress where available, and failure/exit details. **Copy details** provides
a redacted log tail; **Open full log file** opens the local per-run log.
Silent-but-running and missing-heartbeat states are shown explicitly, rather
than implying an endless spinner is progress. See the
[preparation troubleshooting guide](docs/RUN_FROM_SOURCE.md#setup-appears-stuck-at-preparing-your-private-ios-disk)
for log locations and timeout behavior.

## Current status and scope

| Area | What has actually been checked |
| --- | --- |
| Desktop source | Native Windows window, embedded viewer, local IPA preparation, transfer, registration and launch |
| Guest setup | Prepared-root import plus full assembly of all three pinned Apple components into a new private HFSX image; final read-only filesystem verification passed |
| App acceptance | The supplied ARM64 iOSNova app registered and ran as a real iOS process; its Simple screen rendered |
| Initial firmware download | All pinned Apple firmware components downloaded and passed archive integrity checks |
| Clean-PC first run | Public dependency launch and full firmware-to-filesystem preparation checked; first iOS boot of that freshly assembled image remains unverified |
| Running the source | Fresh public clone passed with no Python/developer tools on PATH; `start.cmd` downloaded its runtime and opened the native window; a repeat run reused it |
| Public dependencies | Immutable Windows x64 runtime pack published for the launcher; it contains no Apple firmware or private guest data |

The [Windows clone-and-run check](https://github.com/danhol86/ios-sweet/actions/workflows/studio-source-launch.yml)
also tests dependency preparation, the source regression suite, and cache reuse
on a separate GitHub-hosted Windows runner. Desktop-bootstrap acceptance is
separate from the first iPhone firmware/boot acceptance described above.

This preview targets **Windows 10/11 x64 (Intel/AMD)**, not every machine.
It accepts **unencrypted ARM64 iOS-device IPAs compatible with iOS 16.7.16**;
not every accepted IPA is guaranteed to run. It does not decrypt App Store
DRM, provision a physical iPhone, or invent an Apple-registerable UDID.
Signing is local to this development guest and requires no Apple signing
credentials. Your source IPA is kept unchanged.

No Apple firmware, SDK, private app, signing key or prepared device disk is
included in Git or the public application package. Firmware must come from
Apple directly or your own authorised local copy. This guest is an
experimental development environment, not a secure personal iPhone.

## Where to start

- **Run Studio:** clone this repo and execute `.\start.cmd`; [normal-user help](docs/RUN_FROM_SOURCE.md).
- **Rebuild all helper binaries:** use [the advanced source-build instructions below](#build-ios-sweet-studio-from-source).
- **Reading just the guide:** [standalone build guide](https://github.com/danhol86/ios-sweet/blob/main/docs/STUDIO_SOURCE_BUILD.md).
- **Existing development guest:** [native Windows notes](https://github.com/danhol86/ios-sweet/blob/main/docs/NATIVE_WINDOWS.md) and [guest installation bridge](https://github.com/danhol86/ios-sweet/blob/main/tools/guest-install/README.md).
- **Dependencies:** the launcher automatically downloads its exact [runtime pack](https://github.com/danhol86/ios-sweet/releases/tag/studio-runtime-v0.2.0-r3). You do not download an installer or the older Docker preview.
- **Original physical-phone port:** preserved in the historical section at the bottom. Its flashing instructions do not apply to desktop Studio.

<!-- STUDIO_SOURCE_BUILD_BEGIN -->
## Build iOS Sweet Studio from source

These are the **Windows desktop application's** build instructions, not the
Redmi flashing instructions. Run PowerShell blocks from the repository root
in the same terminal unless a block explicitly says **macOS** or **container**.
Nothing below requires deleting a disk, disabling Windows security, flashing
a phone, or stopping unrelated Docker containers.

The complete Studio source, guest helpers, installer, tests and this guide
are on the default **`main`** branch of **`danhol86/ios-sweet`**. A normal
clone contains everything in this guide; no feature-branch checkout is
required. The explicit `--branch main` below also documents that choice.

### What is being built

| Component | Build method | Needed on a user's installed PC? |
| --- | --- | --- |
| Studio window, embedded viewer and IPA workflow | Python + pywebview + LIEF | Bundled by PyInstaller; no separate Python installation |
| Windows setup/uninstall executables | .NET Framework C# compiler | Included in the setup package |
| iOS guest installer and network helper | LLVM/LLD + an authorised iPhoneOS SDK | Compiled helpers only; no SDK or developer credentials |
| Offline firmware-preparation appliance | Linux packages built in Docker | Native QEMU runs the resulting kernel/initramfs; Docker is not needed by the installed app |
| Patched XNU kernel | Verified existing artifact, or the repository's macOS CI workflow | Kernel binary only |
| QEMU and local `rcodesign` | Independently verified upstream Windows distributions | Bundled runtime binaries |

This builds **our application and helpers from source**, using external
compiler/runtime dependencies. It is not a claim that the Apple userland is
open source, or that every third-party dependency is rebuilt here. Optional
XNU and QEMU source rebuilds are covered below.

### 1. Prerequisites

Use a **Windows 10/11 x64 Intel or AMD PC**. macOS, Linux and Windows-on-ARM
desktop installers are not currently supported by this build recipe.

Install:

- [Git for Windows](https://git-scm.com/downloads/win).
- [64-bit CPython](https://www.python.org/downloads/windows/). The checked
  development environment uses **Python 3.10 x64**. Use the ordinary CPython
  installer, not an embedded Python ZIP. Other Python versions require their
  own dependency and packaging test.
- [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
  with **Linux containers**, for compiling helpers and the preparation
  appliance. This is a developer dependency, not the installed user's runtime.
- [Node.js](https://nodejs.org/en/download) for the two JavaScript test suites;
  these tests use Node built-ins and do not require `npm install`.
- [GitHub CLI](https://cli.github.com/) for downloading a verified kernel
  workflow artifact or building XNU in your own fork.
- [Microsoft WebView2 Evergreen Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
  to run the desktop GUI from source. The installer has its own WebView2
  bootstrap, but running Python directly does not install it for you.
- The Windows .NET Framework compiler at
  `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` for producing the
  setup executable. **Installing a modern `dotnet` SDK alone does not replace
  this exact compiler path** used by `desktop/build.py`.
- For rebuilding the iOS helpers: an **iPhoneOS SDK from your authorised
  Xcode installation**. A simulator SDK is not a substitute. Do not download
  repackaged SDKs from untrusted mirrors or commit an SDK to this repository.

Allow at least **35 GB free on the device-data drive** for first-run firmware
preparation, plus build output and Docker image space. Budget more when
rebuilding all dependencies. Starting the iPhone requires **6 GiB of free
physical RAM**, not merely 6 GiB of installed RAM; 32 GB total is a useful
development-machine target when also running Docker. These are memory and
storage requirements, not an indication that hardware acceleration is used:
ARM64 iOS runs under QEMU TCG software emulation.

### 2. Clone the correct branch and create an isolated Python environment

```powershell
git clone --branch main https://github.com/danhol86/ios-sweet.git
if ($LASTEXITCODE -ne 0) { throw 'Clone failed' }
Set-Location ios-sweet

$Repo = (Resolve-Path .).Path
$Work = Join-Path $Repo 'windows-runtime\desktop-build'
$Assets = Join-Path $Work 'assets'
$Qemu = Join-Path $Repo 'windows-runtime\qemu'
New-Item -ItemType Directory -Force -Path $Work, $Assets, $Qemu | Out-Null

py -3.10 -m venv (Join-Path $Work 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Install CPython 3.10 x64 first' }
$Py = Join-Path $Work 'venv\Scripts\python.exe'
& $Py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed' }
& $Py -m pip install -r desktop/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Pinned Python dependency installation failed' }

& $Py -c "import struct; assert struct.calcsize('P') == 8; import webview, lief, PIL; print('64-bit Python dependencies ready')"
if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed' }
node --version
gh --version
docker info --format '{{.OSType}}'
$Csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $Csc)) { throw 'Required .NET Framework compiler is missing' }
```

Docker's OS type must be `linux`. No PowerShell activation or execution-policy
change is needed because all Python commands explicitly use `$Py`.

Keep `$Repo` and the data directory on a local drive, preferably outside
OneDrive. QEMU preparation rejects paths containing **commas**. The generated
`windows-runtime/` tree is already ignored by Git; never add it with `git add -f`.

### 3. Supply a complete native Windows QEMU installation

Obtain a 64-bit Windows distribution through the
[official QEMU download page](https://www.qemu.org/download/). This project
has been exercised with the QEMU 11.1 development build recorded in
[the component notices](https://github.com/danhol86/ios-sweet/blob/main/desktop/THIRD_PARTY_NOTICES.md).
A different release needs its own boot/install test; do not equate a newer
version with verified compatibility.

Install/extract QEMU to a normal tools folder, then copy its **whole runtime
directory**, not just three EXEs, into this fresh clone:

```powershell
$InstalledQemu = (Resolve-Path (Read-Host 'Full path of your installed Windows QEMU folder')).Path
Copy-Item -Path (Join-Path $InstalledQemu '*') -Destination $Qemu -Recurse

foreach ($name in @('qemu-system-aarch64.exe', 'qemu-system-x86_64.exe', 'qemu-img.exe',
                    'COPYING', 'COPYING.LIB', 'README.rst')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Qemu $name))) { throw "Missing QEMU file: $name" }
}
if (-not (Test-Path -LiteralPath (Join-Path $Qemu 'share\bios-256k.bin'))) {
    throw 'Keep QEMU firmware/ROM files as well as DLLs and executables'
}
& (Join-Path $Qemu 'qemu-system-aarch64.exe') --version
& (Join-Path $Qemu 'qemu-system-x86_64.exe') --version
& (Join-Path $Qemu 'qemu-img.exe') --version
```

The ARM64 executable runs iOS. The x86-64 executable runs only the offline
Linux setup appliance. Keep upstream license files and the distribution's
support DLLs. A missing user-network/slirp feature or ROM is not fixed by
copying an arbitrary DLL from another QEMU version.

### 4. Download and verify the local Windows signer

The signer makes an **ad-hoc development signature inside your private
emulator**, not an Apple Developer provisioning profile. It never needs your
Apple ID, `.p8`, developer certificate, UDID or a hosted signing service.

```powershell
$SignerUrl = 'https://github.com/indygreg/apple-platform-rs/releases/download/apple-codesign%2F0.29.0/apple-codesign-0.29.0-i686-pc-windows-msvc.zip'
$SignerZip = Join-Path $Work 'rcodesign.zip'
$SignerHash = 'fd5aeb908f1d3be60f7e372003772f52a6ce4148106d3aaf22aec6861f5d8a5e'
Invoke-WebRequest -UseBasicParsing -Uri $SignerUrl -OutFile $SignerZip
if ((Get-FileHash -LiteralPath $SignerZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SignerHash) {
    throw 'Signer archive SHA-256 mismatch; do not run it'
}
Expand-Archive -LiteralPath $SignerZip -DestinationPath (Join-Path $Work 'signer')
$Signer = (Get-ChildItem (Join-Path $Work 'signer') -Recurse -Filter rcodesign.exe |
    Select-Object -First 1).FullName
if (-not $Signer) { throw 'Signer executable not found' }
& $Signer --version
if ($LASTEXITCODE -ne 0) { throw 'Signer could not start' }
```

The `i686` archive name is intentional: that specific upstream Windows signer
asset is the verified pin, while Studio and QEMU are x64. A rerun should use
a new build directory or reuse a previously verified signer; do not extract
over unrelated files.

### 5. Obtain the exact verified XNU kernel

For a desktop-source build, use the known-good kernel from this repository's
successful [XNU build run](https://github.com/danhol86/ios-sweet/actions/runs/41191163506).
It includes the quiet-AKS logging patch and has passed local app-launch tests.
GitHub Actions artifacts may expire; the alternative source rebuild is in
step 12, not a reason to use an unrelated kernel.

```powershell
gh auth login
$KernelOut = Join-Path $Work 'xnu-41191163506'
gh run download 41191163506 --repo danhol86/ios-sweet --name xnu-kernel --dir $KernelOut
if ($LASTEXITCODE -ne 0) { throw 'Kernel artifact unavailable; see the XNU rebuild section' }
$Kernel = Join-Path $KernelOut 'kernel.development.sweet'
$KernelHash = '7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8'
if ((Get-FileHash -LiteralPath $Kernel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $KernelHash) {
    throw 'Unexpected kernel build; the verified pin must match'
}
Copy-Item -LiteralPath $Kernel -Destination (Join-Path $Assets 'kernel.aks-quiet.sweet')
```

This is the open-source kernel build, **not the Apple iOS root filesystem**.
No prepared iOS disk is needed just to compile/package Studio.

### 6. Build the public helper toolchain and supply your SDK

This replaces the developer's former private worker-image dependency. It
builds from Ubuntu 24.04 and LLVM's signed package repository; it does **not**
download an Apple SDK or copy one into the Docker image.

```powershell
docker build --platform linux/amd64 --file desktop/helper-toolchain.Dockerfile `
    --tag iossweet-studio-helper-builder:local desktop/appliance
if ($LASTEXITCODE -ne 0) { throw 'Helper toolchain build failed' }
docker run --rm --network none iossweet-studio-helper-builder:local `
    /usr/lib/llvm-23/bin/clang --version
```

**On the Mac with your authorised Xcode installation**, obtain the **device**
SDK and preserve its symlinks in a private archive:

```bash
# macOS terminal; this is not a PowerShell command.
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
test -f "$SDK/SDKSettings.plist"
tar -czf "$HOME/Downloads/iossweet-iphoneos-sdk.tar.gz" -C "$SDK" .
```

Transfer that archive privately to your Windows build machine. Import it into
a dedicated Docker volume so SDK symlinks are not flattened on Windows:

```powershell
$SdkArchive = (Resolve-Path (Read-Host 'Full path to your authorised iossweet-iphoneos-sdk.tar.gz')).Path
docker volume create iossweet-studio-sdk
if ($LASTEXITCODE -ne 0) { throw 'SDK volume creation failed' }
docker run --rm --network none `
    --mount "type=bind,src=$SdkArchive,dst=/input/iphoneos-sdk.tar.gz,readonly" `
    --mount 'type=volume,src=iossweet-studio-sdk,dst=/opt/apple/sdk' `
    iossweet-studio-helper-builder:local sh -c `
    'test ! -e /opt/apple/sdk/SDKSettings.plist || { echo SDK_ALREADY_PRESENT; exit 1; }; tar -xzf /input/iphoneos-sdk.tar.gz -C /opt/apple/sdk && test -f /opt/apple/sdk/SDKSettings.plist'
if ($LASTEXITCODE -ne 0) { throw 'SDK import failed or the private volume is already populated; do not overwrite it blindly' }
```

Keep this SDK volume and archive private. A developer who already has a
working SDK at a local path may bind-mount that directory read-only instead.
The important directory inside the build container is `/opt/apple/sdk`.

### 7. Compile and sign the guest helpers

```powershell
docker run --rm --network none --memory 1g `
    --mount "type=bind,src=$Repo,dst=/src,readonly" `
    --mount "type=bind,src=$Assets,dst=/out" `
    --mount 'type=volume,src=iossweet-studio-sdk,dst=/opt/apple/sdk,readonly' `
    iossweet-studio-helper-builder:local
if ($LASTEXITCODE -ne 0) { throw 'iOS guest helper compilation failed' }

& $Signer sign --timestamp-url none `
    --binary-identifier org.iossweet.development-agent `
    --entitlements-xml-file tools/guest-install/agent-entitlements.plist `
    (Join-Path $Assets 'iossweet-agent')
if ($LASTEXITCODE -ne 0) { throw 'Guest-agent local signing failed' }

docker run --rm --network none `
    --mount "type=bind,src=$Assets,dst=/out,readonly" `
    iossweet-studio-helper-builder:local file /out/iossweet-agent /out/iossweet-net-seed
```

Both helpers must be ARM64 Mach-O files. **Do not omit the agent's
entitlements signing step**: successful C compilation alone does not grant
the guest its app-management capabilities. The network helper receives its
local ad-hoc code signature from the linker. The build script accepts
`IOS_SWEET_CLANG` and `IOS_SWEET_SDK` overrides inside the container, but a
different toolchain or SDK still requires a real boot/install verification.

### 8. Build the offline preparation appliance

Build the helper filesystem tools, then the appliance. The second Dockerfile
uses the first image by its exact local tag, so run these in order:

```powershell
docker build --platform linux/amd64 --tag iossweet-offline-disk-tools:local tools/guest-install
if ($LASTEXITCODE -ne 0) { throw 'Filesystem tool image build failed' }
docker build --platform linux/amd64 --file desktop/appliance/Dockerfile `
    --tag iossweet-studio-preparer:build desktop/appliance
if ($LASTEXITCODE -ne 0) { throw 'Preparation appliance image build failed' }

docker run --rm --network none --memory 2g `
    --mount "type=bind,src=$Repo,dst=/src,readonly" `
    --mount "type=bind,src=$Assets,dst=/out" `
    iossweet-studio-preparer:build
if ($LASTEXITCODE -ne 0) { throw 'Preparation kernel/initramfs export failed' }
```

The result must include `prepare-kernel`, `prepare-initrd.gz`, and component
license/package notices under `$Assets\licenses`. The build uses the pinned
apfs-fuse source revision in the Dockerfile. Ubuntu/LLVM package repositories
can change, so these commands are a source-build recipe, not a claim of
bit-for-bit reproducibility across future package updates. Keep the exported
package inventory with your build.

### 9. Create and validate the helper manifest

Before writing the manifest, build the native Windows firmware decoder.
This maintainer-only step needs an x64 **LLVM-MinGW** compiler on PATH
(`clang --version` must identify the Windows GNU target). Alternatively
pass its full path through `-Clang`. End users do not need this compiler;
the source launcher downloads the verified runtime binary automatically.

```powershell
.\desktop\build-lzfse.ps1 -OutputDirectory $Assets
if ($LASTEXITCODE -ne 0) { throw 'Native firmware decoder build failed' }
```

The script checks out a pinned public LZFSE revision, retains its license
and provenance, and creates `$Assets\lzfse.exe`. It does not download Apple
firmware. Studio fetches the 33 KB private iPhone DeviceTree from Apple on
first setup/start; neither that `.im4p` nor the extracted `.adt` belongs in
the repository or a public dependency ZIP.

Only create a manifest **after** verifying the upstream downloads and
successfully compiling/signing the helpers. Generating a hash is not a
substitute for establishing where a file came from.

```powershell
@'
from pathlib import Path
import hashlib, json, sys
assets = Path(sys.argv[1])
names = ('prepare-kernel', 'prepare-initrd.gz', 'iossweet-agent',
         'iossweet-net-seed', 'kernel.aks-quiet.sweet', 'lzfse.exe')
manifest = {}
for name in names:
    path = assets / name
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit('Missing or empty helper: ' + name)
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    manifest[name] = digest.hexdigest()
expected = '7dc86497ccd0c224ec1e6b8430be6f2dd7a46ac13ef795ed4047d0adf7d3bde8'
if manifest['kernel.aks-quiet.sweet'] != expected:
    raise SystemExit('Kernel does not match the verified Studio pin')
(assets / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('HELPER_MANIFEST_READY')
'@ | & $Py - $Assets
if ($LASTEXITCODE -ne 0) { throw 'Helper manifest validation failed' }
```

Your source checkout should now contain the following **ignored, private
build-output layout**, with no dependency on the original developer's paths:

```text
windows-runtime/
  qemu/                         # native Windows distribution, DLLs and ROMs
  desktop-build/
    venv/Scripts/python.exe
    signer/.../rcodesign.exe
    assets/
      manifest.json
      prepare-kernel
      prepare-initrd.gz
      iossweet-agent
      iossweet-net-seed
      kernel.aks-quiet.sweet
      licenses/...
```

### 10. Run tests and start the application from source

```powershell
& $Py -m unittest discover -s tests -p 'test_*.py' -q
if ($LASTEXITCODE -ne 0) { throw 'Python tests failed' }
node tests/check_viewer_poll.js
if ($LASTEXITCODE -ne 0) { throw 'Viewer scheduling test failed' }
node tests/check_viewer_pointer.js
if ($LASTEXITCODE -ne 0) { throw 'Viewer pointer/gesture tests failed' }
& $Py desktop/studio.py --self-test
if ($LASTEXITCODE -ne 0) { throw 'Desktop resource check failed' }

# Separate development device data from any existing installed Studio profile.
$env:IOS_SWEET_HOME = Join-Path $Work 'dev-data'
& $Py desktop/studio.py
```

Stop any existing iOS Sweet VM before creating a new device. Studio enforces
a single desktop instance and validates the running QEMU process before
reusing/stopping it. **Closing the Studio window does not necessarily stop
the iPhone**; use **Stop** in Studio before backing up or changing a device.

In the GUI:

1. Open **Device setup**. Choose **Download & create iPhone** after confirming
   you are authorised to use the firmware. Studio fetches the pinned iPhone X
   iOS 16.7.16 components directly from Apple and builds its private device.
   Alternatively, import your own prepared **16 GiB HFSX `.raw`/`.img`** with
   **Choose root image → Create device**. An `.ipsw`, APFS DMG or QCOW2 file is
   not a prepared root image and cannot be substituted into this import step.
2. Press **Start iPhone**. Wait for the guest to finish booting, then use
   **Home / unlock** as necessary. Initial boot and application rendering
   can be slow because this is CPU-only ARM64 emulation.
3. Choose **Choose IPA file → Install & launch**. Studio validates the IPA,
   works on a private copy, locally signs/relocates embedded libraries,
   transfers it through the authenticated guest agent, registers it with iOS
   and verifies that the requested app process runs. Inspect the embedded
   screen to confirm that the app actually renders.
4. Installed applications appear in the library with **Open** and **Stop**.
   Stop a running app before updating it. An app failing compatibility checks
   is rejected; the tool does not decrypt App Store DRM or silently replace
   the original IPA.

**Acceptance boundary:** the development build has successfully created a
guest from a prepared root and installed/launched the supplied iOSNova IPA.
Downloading all pinned Apple components also passed. The complete fresh-PC
**Apple download → new root → boot → install** workflow and the rebuilt
installer still need an independent clean-machine acceptance test. Automated
tests and a successful package build do not prove that last workflow.

### 11. Build the portable ZIP and one-click Windows installer

Close the source GUI first. Keep device data outside the output directory.
Use a **new output folder** for each build to avoid retaining stale staged
files from an older build:

```powershell
$Release = Join-Path $Work ('release-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $Py desktop/build.py --assets $Assets --qemu $Qemu --signer $Signer --output $Release
if ($LASTEXITCODE -ne 0) { throw 'Desktop/installer build failed' }

Get-ChildItem -LiteralPath $Release -File | Select-Object Name, Length
Get-Content -LiteralPath (Join-Path $Release 'iOS-Sweet-Studio-Setup.exe.sha256')
Get-FileHash -LiteralPath (Join-Path $Release 'iOS-Sweet-Studio-Setup.exe') -Algorithm SHA256

$App = Join-Path $Release 'portable\iOS Sweet Studio\iOS Sweet Studio.exe'
$Check = Start-Process -FilePath $App -ArgumentList '--self-test' -Wait -PassThru
if ($Check.ExitCode -ne 0) { throw 'Frozen application resource check failed' }
```

Expected outputs:

| Output | Purpose |
| --- | --- |
| `iOS-Sweet-Studio-Setup.exe` | Per-user Windows installer with embedded application payload |
| `iOS-Sweet-Studio-Setup.exe.sha256` | Installer integrity checksum |
| `iOS-Sweet-Studio-Windows-x64.zip` | Portable application folder; extract the whole ZIP |
| `iOS-Sweet-Studio-Windows-x64.zip.sha256` | Portable-package integrity checksum |
| `portable/iOS Sweet Studio/` | Uncompressed application and `_internal` runtime resources |

The public package allowlist must exclude Apple IPSWs, `.dmg`/`.raw`/`.qcow2`
images, private IPAs, SDKs, `device.json`, `bridge.json`, credentials and signing
keys. Review the archive rather than assuming `.gitignore` is a packaging
security boundary. Keep third-party licenses and component sources available
when redistributing their binaries.

The current setup is **not Authenticode-signed**; a Windows publisher warning
is expected. Do not instruct users to disable SmartScreen/antivirus. For a
public release, use an appropriate Windows code-signing certificate and
recalculate checksums **after signing**. App ad-hoc signing inside iOS Sweet
does not sign or authenticate the Windows installer.

Test the EXE on a clean Windows account/PC, not only on the build machine:
installation, WebView2 bootstrap when absent, firmware setup, GUI start,
IPA installation, restart persistence, update safety and uninstall. Confirm
uninstall leaves the separate device-data folder intact. Only after that
publish the EXE/ZIP/checksums as a clearly labelled preview release.

### 12. Rebuild the XNU kernel or external dependencies

**XNU from source:** fork this repository under an account you control, enable
Actions, and ensure your fork has the `main` branch. The checked-in
[`xnu.yml` workflow](https://github.com/danhol86/ios-sweet/blob/main/.github/workflows/xnu.yml)
uses a macOS runner, Apple's open XNU sources and this repository's ordered
patch series. You can trigger it from Windows:

```powershell
$KernelRepo = Read-Host 'Your fork in owner/ios-sweet form'
gh workflow run xnu.yml --repo $KernelRepo --ref main `
    -f macos_version=13.5 -f kernel_config=DEVELOPMENT -f machine_config=SWEET
if ($LASTEXITCODE -ne 0) { throw 'Workflow dispatch failed' }
gh run list --repo $KernelRepo --workflow xnu.yml --branch main --limit 5
$RunId = Read-Host 'Run ID belonging to the workflow you just started'
gh run watch $RunId --repo $KernelRepo --exit-status
if ($LASTEXITCODE -ne 0) { throw 'XNU build failed; inspect its logs' }
$CustomKernelOut = Join-Path $Work ('xnu-custom-' + $RunId)
gh run download $RunId --repo $KernelRepo --name xnu-kernel --dir $CustomKernelOut
if ($LASTEXITCODE -ne 0) { throw 'Kernel artifact download failed' }
Get-Content (Join-Path $CustomKernelOut 'SHA256SUMS')
Get-FileHash (Join-Path $CustomKernelOut 'kernel.development.sweet') -Algorithm SHA256
```

A successful CI run is **not proof of guest compatibility**. A newly compiled
kernel may have a different digest even with the same patches. To intentionally
adopt it, first verify its artifact checksum, inspect the changes, then update
the `QUIET_KERNEL` pin in `desktop/runtime_setup.py`, copy the new binary to
`$Assets\kernel.aks-quiet.sweet`, and regenerate the manifest using that exact
reviewed hash instead of the step-9 baseline hash. Test on a separate private
device and retain the previous kernel/overlay. Do not remove hash checks or
replace a running user's kernel as part of documentation setup.

**QEMU from source:** use QEMU's
[Windows/MSYS2 build-environment instructions](https://www.qemu.org/docs/master/devel/build-environment.html).
Build the Windows `aarch64-softmmu` and `x86_64-softmmu` system targets and
`qemu-img`, including slirp/user networking, QCOW2/raw/FAT support and the
matching firmware/DLLs. Stage a complete installation in `$Qemu` and retain
the upstream license/README files required by `desktop/build.py`. This is an
optional external-dependency rebuild, not a tested replacement for the known
Windows distribution.

**Signer from source:** the pinned
[apple-platform-rs 0.29.0 release](https://github.com/indygreg/apple-platform-rs/releases/tag/apple-codesign%2F0.29.0)
contains its own Rust source/build instructions. A replacement binary must
be tested for signing both the entitled agent and nested app frameworks before
passing its path to `desktop/build.py`.

### 13. Troubleshooting, logs and safe updates

| Symptom | Check / next action |
| --- | --- |
| `desktop/studio.py` is missing after clone | Confirm the remote is `danhol86/ios-sweet`, not upstream `dipa-studio/ios-sweet`, then switch to `main` and update with `git pull --ff-only`. An old checkout may predate Studio. |
| Python package import fails | Use the venv's `$Py`, install `desktop/requirements.txt`, and confirm 64-bit CPython. Do not mix Python installations. |
| GUI fails to create its browser window | Install the WebView2 Evergreen x64 runtime and verify .NET Framework/Python.NET dependencies; see [pywebview's installation guide](https://pywebview.flowrl.com/guide/installation). |
| Compiler or SDK not found | Build `desktop/helper-toolchain.Dockerfile`; mount the device SDK at `/opt/apple/sdk`; check `SDKSettings.plist` and `clang --version`. |
| Shell script fails with `\r` / bad interpreter | Honour the repository's `.gitattributes` LF rules for `.sh`, Dockerfiles and appliance `init`. Do not edit these with forced CRLF line endings. |
| Appliance cannot mount its FAT job volume | Rebuild the **current** appliance sources, including the module decompression step. Review `prepare.log`; do not substitute an old initramfs. |
| Missing helper or SHA-256 mismatch | Verify provenance, rebuild/copy the intended helper, then regenerate `assets/manifest.json`. Do not blindly approve an unexpected kernel hash. |
| Kernel artifact expired or `gh` returns 404 | Authenticate with the correct account/repository, then use the documented XNU source-build route if the old artifact is no longer retained. |
| Startup reports insufficient RAM | Free memory by closing your own unused work. Do not remove the 6 GiB guard or kill unrelated WSL/Docker services. |
| A second guest or conflicting port exists | Stop the previous iOS Sweet instance cleanly. Only reuse a matching configured device; do not kill an arbitrary process on port 8108/4444. |
| IPA validation fails | Use your own unencrypted ARM64 **device** IPA that supports iOS 16.7.16; not an Intel/simulator, ARM64e-only, DRM-encrypted or newer-iOS-only binary. |
| Updating an app says it is running | Select **Stop** for that app, verify it has exited, then install the update. The source IPA is never overwritten. |
| App is installed but does not render | A registration record or running process alone is not UI compatibility. Inspect the embedded screen and guest logs; do not mark the app supported yet. |
| Installer self-test passes but first-run fails | The self-test checks packaged resources, not firmware preparation, iOS boot, signing/installation or a clean-machine GUI. Complete the acceptance test. |

By default, Studio device data lives under `%LOCALAPPDATA%\iOS Sweet Studio`.
The setup wizard can select another drive, and source runs can use
`IOS_SWEET_HOME`. Inside it, `logs/` contains host logs, `jobs/` contains
per-install preparation/signing reports, `device.json` identifies the selected
device, and `devices/<id>/prepare.log` records offline disk creation. The
`devices/<id>/ios.raw` base, its QCOW2 overlay and its bridge capability are
private. Never upload the whole data directory to a bug report.

Use **Open logs** in Studio. Before copying a device, press **Stop**, verify
the matching QEMU process has exited, and keep the base image together with
the overlay (QCOW2 backing paths matter). Application-code updates should
not overwrite the device-data directory. Rebuilding a package does not
automatically upgrade a guest agent already installed in an older device.

When sharing a test result, record the repository commit, Python/dependency
versions, QEMU version, kernel hash, helper manifest, host OS, and the
sanitised build/boot logs. Include whether the app was merely transferred,
registered, started as a process, or visibly rendered and interacted with.

### Upstream references

- [pywebview Windows dependencies](https://pywebview.flowrl.com/guide/installation)
- [Microsoft WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
- [LLVM signed Ubuntu repositories](https://apt.llvm.org/)
- [QEMU downloads](https://www.qemu.org/download/) and [build environments](https://www.qemu.org/docs/master/devel/build-environment.html)
- [Apple SDK/Xcode distribution](https://developer.apple.com/xcode/resources/)
- [Component provenance and notices](https://github.com/danhol86/ios-sweet/blob/main/desktop/THIRD_PARTY_NOTICES.md)

The root README includes this guide in full. Update both copies together; the
documentation check verifies that the README's source-build block matches.
<!-- STUDIO_SOURCE_BUILD_END -->

---

<details>
<summary>Historical Redmi Note 10 Pro port and earlier Windows/Docker notes</summary>

The material below is preserved engineering history. Dates, hardware claims
and older Docker installation steps do not override the Studio status and
source-build requirements above. Desktop users should not flash a phone.

**Native Windows IPA test (2 November 2026):** the supplied `com.iosnova`
IPA has now been locally signed, registered with the guest's LaunchServices,
launched as a real iOS process, and rendered its interactive **Simple**
sign-in / Create account screens. See [IPA installation](docs/IPA_INSTALLATION.md)
and the [isolated guest bridge](tools/guest-install/README.md).

This uses a **local development installation path**, not Apple Ad Hoc device
provisioning. The guest still reports only a placeholder identity, not an
Apple-registerable UDID; no fake hardware identifier is submitted to Apple.
Only the supplied app has passed the full install-and-render acceptance test.

**Apple's iOS 16 running on a Redmi Note 10 Pro.**

This project ports Apple's open-source XNU kernel (xnu-8796, the iOS 16 generation) to the Xiaomi Redmi Note 10 Pro (`sweet`, Qualcomm SM7150 / Snapdragon 732G). On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd, SpringBoard and the stock apps.

As of **2026-10-18** the phone boots to the **iOS home screen**. You can unlock it, open Settings, pull down Control Center and the notification center, and use the touchscreen and the hardware buttons. Rendering runs entirely on the CPU; there is no GPU driver.

## Windows / Docker preview — install from GitHub

For **Windows**, download the
**[Docker preview installer ZIP](https://github.com/danhol86/ios-sweet/releases)**,
extract it and double-click **`Install-iOS-Sweet.cmd`**. The installer can
install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
using Windows Package Manager if needed (UAC and a restart may be required).
It uses Linux containers but does **not** require a separate Ubuntu WSL
distribution.

**Important:** This public download contains the installer, Docker scripts,
and our network bootstrap, **not a bootable Apple operating system**. Newer
installer versions automatically retrieve the verified open-source XNU kernel,
then download official iPhone X iOS 16.7.16 firmware directly from Apple
and prepare a **private** iOS HFSX disk locally. The first preparation needs
at least **35 GiB of free disk space** and may require a substantial download.
Manual file pickers remain available if automatic preparation cannot work
on your machine. See the
**[GitHub installation guide](docs/GITHUB_INSTALL.md)** for preparation steps
and the [Docker-only technical notes](docs/ONE_CLICK_DEPLOY.md).

The iOS GUI and Safari launch. Guest DNS/TCP connectivity is verified,
and the **native Windows QEMU** setup has rendered real external HTTPS
pages in Safari. Some pages or fresh sessions may still render blank or
take an unusually long time to repaint. This remains an experimental
development preview, not a complete or fast iOS simulator. The installer
never flashes the phone.

### Direct Windows QEMU runtime (development branch)

There is also an experimental **native Windows QEMU** launch path that does
not run the emulator in Docker or WSL. Install Windows QEMU, supply the
locally prepared private iOS disk and verified kernel, then double-click
`Start-iOS-Sweet-Windows.cmd`. It preserves the previous Docker guest
overlay by making a separate copy for Windows. See
**[Native Windows installation and limitations](docs/NATIVE_WINDOWS.md)**.

On x86 Windows, the verified QEMU build offers **TCG software emulation,
not hardware-accelerated ARM64**. A substantial speedup is not guaranteed,
and the 7 GiB iOS guest requires enough free host memory. On 30 October
2026 the native Windows QEMU guest reached the lock screen, home screen
and Safari using its preserved private save. Its initial Safari attempt
rendered blank; subsequent tests on 30-31 October successfully loaded Google
over HTTPS, including its real consent UI. Rendering remains very slow.

On the tested PC, QEMU, the private 16 GiB iOS disk, kernel, writable
overlay and logs live under `D:\Projects\ios-sweet\windows-runtime`.
The dedicated iOS Sweet Docker containers, images and generated firmware
working files were removed. Unrelated Docker Desktop services were
left running.

**Updated 30 October 2026:** A later live Windows run (with the optional
software sRGB display mode) successfully rendered Google's HTTPS page and
consent dialog and the independently hosted `https://example.com` page in
Safari, both with secure HTTPS lock icons. A local HTTP control loaded HTML, CSS,
text, an image and a JavaScript-requested resource. This establishes that
browser networking and rendering *can* work, though the unaccelerated
ARM64 guest is still extremely slow. Repeatability across websites and
fresh boots is not yet fully validated; see `docs/SAFARI_NETWORK_DIAG.md`.

**31 October 2026 follow-up:** The Windows 2-CPU build is now verified across
multiple boots, including Safari rendering Google over HTTPS. Its locally
optional `0098` quiet-logging kernel successfully booted and rendered the
same real external HTTPS page, both on an isolated candidate disk and from
the one-click Windows launcher with the original preserved two-core save.
The original single-core kernel/disk remain available for rollback; Docker
and physical-phone kernel pins are unchanged. Running users can check their
live Windows instance without modifying the guest using
`powershell -NoProfile -File tools/Test-IosSweet-Windows.ps1`.
This is still **software-emulated ARM64**, with significant performance
limitations and no demonstrated long-term stability guarantee.

**31 October:** An isolated two-core native Windows guest reached SpringBoard,
loaded Google over HTTPS, and displayed example.com over HTTP. It also
booted a second time with diagnostics disabled and loaded the HTTP page
again. The live viewer has frame caching, adaptive refresh, faster PNG
encoding and a batched Home gesture. The Windows test PC uses a **local-only
two-core preference** with a saved single-core fallback; new installations
continue to default to one core. See `docs/NATIVE_WINDOWS.md`.

> **Physical-phone installation only:** Experimental bring-up, not a usable phone OS. Many things are missing or stubbed (see below), and Apple's security model is mostly switched off. Flashing the phone installs into the `userdata` partition and so **erases Android's user data**. The Windows/Docker installer does not flash a phone.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi bootloader → `fastboot boot` of our shim → XNU. Nothing is flashed to the boot partitions |
| CPU | 6 of the 8 cores (the six Cortex-A55s) via PSCI, 16K pages, GICv3 interrupts, timers |
| Memory | About 3.95 GiB of the upper DDR bank |
| Storage | Own UFS host driver; the iOS root is a journaled HFS+ volume in `userdata`, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem and shared cache; launchd and the system daemons run |
| Display | Kernel IOSurface + IOMobileFramebuffer (`AppleCLCD`) services; CoreAnimation renders in software; frames are copied into the bootloader's framebuffer. Presented to iOS as an iPhone X panel (1125×2436) |
| GUI | backboardd, SpringBoard, lock screen, home screen, Control Center, notification center, Settings |
| Touch | Goodix GT9896 over I²C (GENI), rail enabled through RPMh, delivered as HID digitizer events |
| Buttons | Power, volume up/down (PMIC through SPMI) as HID consumer keys; lock/wake works |
| Battery | IOPMPowerSource service (static 100 %, charging icon; real fuel-gauge readout prepared) |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI |
| Activation | Native "Hactivation" path of mobileactivationd, chosen through device-tree security status. No Apple servers involved |

## What does not work (yet)

- **Navigation:** you cannot leave an app (the home gesture and AssistiveTouch Home do nothing yet).
- **No Wi-Fi, Bluetooth, cellular, audio, camera, sensors, GPS or SEP / Face ID.** Daemons for them start and fail or keep relaunching.
- **No GPU.** Everything is drawn by the CPU at roughly 20–30 fps. The two Cortex-A76 cores are not used yet.
- **Few apps.** The image has only what is on the system volume. There is no App Store, no Apple ID, and some Settings pages are empty.
- **Slow boot:** about 4 minutes on the Apple logo.
- **Security is off:** permissive code signing (AMFI) and sandbox policies, a stub AppleKeyStore, no data protection. Do not put anything personal on it.

## How it boots

```
ABL (stock Xiaomi bootloader, unlocked)
  -> fastboot boot shim-boot.img              (temporary; nothing is flashed to boot)
     -> shim: own MMU setup, reads the live FDT, loads the payload from the ramdisk
        -> XNU Mach-O + generated Apple Device Tree (ADT) + boot-args
           -> XNU -> UFS driver -> HFS+ root in the userdata partition
              -> dyld + shared cache -> launchd -> daemons -> backboardd + SpringBoard
```

There is no serial port (the debug UART is wired as SPI on this board). The kernel draws its console into the framebuffer that ABL leaves at `0x9c000000`, and keeps a persistent 4 MiB log ring at the end of `userdata`. You read that log from OrangeFox recovery with `tools/sweet-log-pull.sh`, so you don't have to film the screen.

## How to do it yourself

You need a Redmi Note 10 Pro (`sweet`, global or Indian variant, SM7150) with an **unlocked bootloader**, a Linux PC, and a GitHub account for the kernel build. This is the exact path used for the screenshots above; other variants or firmware may need changes. **Everything on `userdata` is lost.** Bootloaders, recovery, modem and persist partitions are never touched.

### 0. Back up the phone

Boot OrangeFox (or any recovery with adb root) temporarily and pull at least `persist`, `modemst1`, `modemst2`, `fsg`, `fsc` and `boot`, `dtbo`, `vbmeta`. They contain per-device calibration data. Keep them off git; `.gitignore` already excludes `backup/`, `dtb/` and `recovery/`.

The shim needs the stock DTB. Unpack your phone's stock `boot.img`:

```sh
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked   # -> dtb/boot_unpacked/dtb
```

### 1. Build the kernel

The kernel builds on GitHub's macOS runners with [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build). The workflow fetches xnu-8796, applies `xnu/patches/` in order, and also stages the pinned open-source libpthread, HFS and BearSSL sources it needs. Fork the repo (public repos get free macOS minutes) and run:

```sh
gh workflow run xnu.yml -R YOU/ios-sweet
gh run download RUN_ID -R YOU/ios-sweet -n xnu-kernel -D xnu/out
```

To check a patch locally before spending a CI run, `tools/xnu-cc.py` replays the compile commands of a previous CI log for single files.

### 2. Build the iOS root image

Download the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW from Apple. Then, on Linux, with `apfs-fuse`, `hfsprogs` and sudo:

```sh
# OS, SystemOS and AppOS disk images from the IPSW (see BuildManifest.plist for their names)
tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G
sudo fsck.hfsplus -fy ios16-root.img
sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot
sudo python3 tools/sweet-root-tweaks.py /mnt/iosroot
sudo umount /mnt/iosroot
img2simg ios16-root.img ios16-root.simg
```

`mkiosroot.sh` copies the OS volume and both cryptexes into one case-sensitive journaled HFS+ volume. It adds the dyld cache links, the plain system keybag and the log directories the daemons expect. `sweet-root-tweaks.py` applies the bring-up changes: it skips Setup, seeds the activation state, removes the baseband daemon, disables the watchdogs that kill slow apps and the crash-looping media paths, and so on. The script's header explains each change.

The device tree builder copies `/product` from the real iPhone X device tree, which MobileGestalt needs. Extract it once, without downloading the whole IPSW:

```sh
python3 tools/remotezip.py IPSW_URL DeviceTree.d22ap.im4p research/ipsw-x/dt
ipsw img4 im4p extract research/ipsw-x/dt/Firmware/all_flash/DeviceTree.d22ap.im4p -o research/ipsw-x/d22ap.adt
```

### 3. Build the boot image

Needs `aarch64-linux-gnu-gcc` and `mkbootimg`.

```sh
python3 tools/mkadt.py shim/out/sweet.adt --highmem
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/sweet.adt shim/out/payload.bin \
    --cmdline 'debug=0xc serial=3 cpus=6 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30'
shim/build.sh ../shim/out/payload.bin      # -> shim/out/shim-boot.img
```

What the less obvious boot-args do:

| Boot-arg | Effect |
| --- | --- |
| `rd=ufsroot0 ufsrw=1 rootrw=1` | Root on the `userdata` partition, writable |
| `cpus=6` | Start the six A55 cores; `cpus=1` is the safe fallback |
| `launchd_unsecure_cache=1` | launchd accepts its job cache without AMFI |
| `wdt=-1 wdt_test=no_user_checkin` | No hardware watchdog |
| `sweetfb_noconsole=1` | Stop drawing kernel text over the GUI. It still goes to the persistent log; panics are drawn |
| `sweetfb_hz=30` | Panel refresh rate of the CPU copy |
| `sweettouch=0`, `sweetkeys=0` | Disable the touch or button driver |

### 4. Flash the root and boot

```sh
fastboot -S 512M flash userdata ios16-root.simg   # ~7 minutes; do not unplug
# Xiaomi's fastboot often hangs after a large flash: re-enter fastboot with Power + Volume down
fastboot boot shim/out/shim-boot.img
```

The first boot takes about 4–5 minutes on the Apple logo, then the lock screen appears. Swipe up to unlock. To get back to fastboot, hold Power + Volume down.

### 5. Read the kernel log

```sh
fastboot boot recovery/recovery.img        # OrangeFox, temporary
tools/sweet-log-pull.sh logs/boot.txt      # 4 MiB console ring from the end of userdata
adb reboot bootloader
```

The log contains crash reports with backtraces (`CRASH name ...`), IOKit traces of backboardd and SpringBoard, and the drivers' `SWEET ...` lines. `tools/sweet-crash.py` symbolicates them against the shared cache.

### QEMU

**Windows desktop: Docker-only (experimental).** Install Docker Desktop and
double-click `Install-iOS-Sweet.cmd`. This builds a single Docker image,
prepares a private copy-on-write iOS disk with automatic root-owned
IPv4/DNS seeding, and starts the ARM64 QEMU emulator without requiring an
extra Ubuntu/WSL distribution. It saves local source paths and creates
**iOS Sweet (Docker)** on the desktop. The viewer is
`http://127.0.0.1:8108/`. The iPhone X iOS 16.7.16 lock screen and
SpringBoard boot; native guest hostname resolution and outbound TCP now pass.
**Safari page rendering is still experimental and is not yet fully verified.**

The interactive guest requires a locally prepared private test root
with the existing MobileGestalt compatibility workaround. Neither the
modified Apple userland nor any guest firmware is distributed or committed.
The installer includes only our small open-source boot helper; its original
Apple `ReportCrash` target is preserved in the private overlay. See
[Docker-only installation and networking status](docs/ONE_CLICK_DEPLOY.md).

`tools/qemu-sweet.py` boots the same kernel on QEMU `virt` with a test RAM-disk root. It is useful for kernel-only changes; see `NOTES.md`.

## Repository layout

| Path | What |
| --- | --- |
| `shim/` | Bare-metal boot shim (C + asm) packed as an Android boot.img v2 |
| `xnu/patches/` | The XNU patch series (applied in order by CI), plus staging scripts for libpthread, HFS and BearSSL |
| `.github/workflows/xnu.yml` | Kernel CI build |
| `tools/mkadt.py` | Generates the Apple Device Tree from sweet's MMIO layout and the iPhone X identity |
| `tools/mkpayload.py` | Packs kernel + ADT + boot-args into the shim payload |
| `tools/mkiosroot.sh` | Builds the HFS+ iOS root from the IPSW images |
| `tools/sweet-root-tweaks.py` | Bring-up changes to the root (Setup skip, activation, daemons) |
| `tools/sweet-log-pull.sh`, `sweet-log.py` | Read the persistent kernel log from recovery |
| `tools/sweet-crash.py` | Symbolicate console crash reports |
| `tools/xnu-cc.py` | Local single-file compile check from a CI log |
| `tools/qemu-sweet.py` | QEMU test boots with framebuffer text decoding |
| `docker/`, `Install-iOS-Sweet.cmd` | Windows Docker-only installer, QEMU runner, persistent state and viewer |
| `tools/adt.py`, `remotezip.py`, `unpack_bootv2.py`, `sparsediff.py` | Helpers |
| `NOTES.md` | Detailed engineering log: every boot, crash and decision, plus hardware facts |

Not in git: partition backups, live device trees, recovery images, Apple firmware and root images, and downloaded or generated build trees. They contain device serials and calibration data, or Apple's copyrighted files.

## Kernel patches

| # | What |
| --- | --- |
| 0001–0009 | Toolchain compatibility, SWEET machine config, non-PAC arm64, stubs for Apple-internal pieces |
| 0010–0018 | Early framebuffer console, physmap fix, PRNG without corecrypto, device-tree platform expert, timer PPI, boot CPU driver |
| 0019–0020 | Apple open-source libpthread kernel provider; BearSSL AES |
| 0021–0027 | RAM-disk root, mockfs, SHA-256, minimal AMFI, Apple open-source HFS+, MD5 |
| 0028–0034 | UFS host driver and root device, read/write root, DMA above 4 GiB |
| 0035–0045 | Entitlements, bindfs, AppleKeyStore stub, IOWatchdog, console crash reports |
| 0046 | IOSurface (IOCoreSurfaceRoot) and IOMobileFramebuffer (AppleCLCD) services |
| 0047–0055 | Diagnostics: persistent log, /dev/null tee, IOKit trace, heap strings and user stack sampler on crash; permissive Sandbox policy; HFS rename-swap; AppleKeyStore selectors |
| 0056–0057 | Throttled panel copy; no external identity resolver |
| 0058 | HID event services. Apple's IOHIDFamily-1915.140.3 user client and event queue, matching the iOS 16.7 userland |
| 0059 | iPhone X identity (`hw.product` / `hw.target` from the device tree) |
| 0060 | Power and volume keys over SPMI; touch over GENI I²C |
| 0061 | Present the display as 1125×2436 |
| 0062 | RPMh regulator vote for the touch rail; battery power source |
| 0063 | GENI FIFO packing fix and the Goodix GT9896 protocol |
| 0064 | Grant PRIV_WORK_INTERVAL (UIKit's CoreAnimation work interval) |
| 0065 | SMP: secondary A55 cores via PSCI CPU_ON |
| 0066–0067 | Fault-region crash info; console mute |
| 0068 | IOSurface lookup semantics for already-mapped surfaces |
| 0069 | Batched persistent-log flushes |

## Key hardware facts

- RAM: payloads use the upper bank, `0x100000000` + `0xfcc00000` (about 3.95 GiB), above Qualcomm's protected carve-outs.
- GICv3 with security extensions: the timer goes through Group 1 IRQ (virtual timer INTID 19), not FIQ as on Apple silicon.
- PSCI through `smc`, 19.2 MHz timer, ARMv8.2 without pointer authentication. MPIDR uses Aff1 for the core number.
- Panel: 1080×2400 DSC video mode, continuous splash from ABL, no refresh kick needed.
- Touch: Goodix GT9896 at I²C `0x5d` on QUP SE7 (`0xa84000`), powered by PM6150L LDO11 through RPMh.
- Buttons: power and volume down on the PM6150 PON block, volume up on PM6150L GPIO2 (SPMI SID 4).

More in [`NOTES.md`](NOTES.md).

## Credits

Built on Apple's open-source releases (xnu, IOHIDFamily, libpthread, hfs), [BearSSL](https://bearssl.org), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), [ipsw](https://github.com/blacktop/ipsw), Qualcomm/Xiaomi's published Linux kernel sources for the hardware details, and [OrangeFox Recovery](https://orangefox.download). iOS itself is Apple's and is not distributed here.

</details>
