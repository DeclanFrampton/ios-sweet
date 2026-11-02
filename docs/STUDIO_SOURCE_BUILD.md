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
