# Clone, run one command, open Studio

For **Windows 10/11 x64 (Intel or AMD)**, run:

```powershell
git clone https://github.com/danhol86/ios-sweet.git
cd ios-sweet
.\start.cmd
```

After cloning, **`start.cmd` is the only setup/launch command**. Run it again
whenever you want to open Studio. No Studio installer or setup wizard is used.

## What the command does automatically

1. Downloads the source-pinned runtime pack from this repository's GitHub
   Releases and verifies its SHA-256. Each extracted dependency is also
   verified against a separately pinned file inventory.
2. Makes an **application-local Python**, GUI libraries, native Windows QEMU,
   local IPA signer, guest helpers and firmware-preparation engine available
   under `.studio/runtime/`. It does not install a global Python, run `pip`
   on your PC, change your PATH, or replace an existing development environment.
3. Detects Microsoft WebView2. Only when missing, it downloads the Evergreen
   runtime directly from Microsoft, verifies Microsoft's Authenticode
   signature, and requests a silent per-user dependency installation.
4. Checks imports/native executables, then launches **the Studio source from
   your cloned repository**. This is not a disguised frozen-app installer.

You do **not** need Python, Docker, WSL, an Apple SDK, a compiler, Node,
GitHub CLI/login, an Apple Developer account or signing certificates just
to run Studio. Git is needed only for the clone/update operations above.
Administrative elevation is not requested. Windows 10 build 19041 or later
and its .NET Framework runtime are required; Windows 11 is supported.

**Verified source-launch path:** a fresh public clone in a directory with a
space downloaded its empty-cache dependencies and opened the native Studio
window with Python, pip, Docker, Node and GitHub CLI unavailable on PATH.
Repeating `start.cmd` reused the same window. A separate GitHub-hosted Windows
runner passed bootstrap, source tests and cache reuse too. This verification
covers opening Studio; it does not claim every PC or IPA has been tested.

## First time inside the app

The window opens with the embedded iPhone viewer, app library and IPA picker.
The first device still needs its own Apple firmware: confirm the in-app
authorisation checkbox and click **Download & create iPhone**. Studio downloads
the pinned iPhone X components directly from Apple and prepares a private
guest. Existing users can instead import their prepared iOS Sweet root image.

Apple firmware, an SDK, user IPAs, personal certificates, bridge secrets and
prepared iPhone disks are **not** in the repository or public runtime pack.
Allow at least **35 GB free storage** for firmware/device creation and
**6 GiB available RAM** before starting the iPhone. Opening the Studio window
does not itself start another QEMU instance or stop other applications.

Once the iPhone has booted, use **Choose IPA file → Install & launch**.
The app operates on a private copy of the IPA. Unencrypted ARM64 iOS-device
apps compatible with iOS 16.7.16 are the target; not every IPA is guaranteed
to work, and App Store DRM is not removed.

## Where things go

| Location inside the clone | Contents |
| --- | --- |
| `.studio/downloads/` | Verified dependency archive cache |
| `.studio/runtime/<version>/` | Private Python, libraries and native tools |
| `.studio/data/` | Your private devices, overlays, apps, firmware cache and logs |
| `.studio/logs/` | Bootstrap output and download/preflight failures |
| `.studio/data/logs/desktop.stderr.log` | Desktop startup errors |

The entire `.studio/` directory is ignored by Git. **Do not delete it to
update the application**: it contains the private iPhone data. `git pull`
updates source, and the next `start.cmd` verifies/reuses its dependencies.
Changed runtime versions are installed side-by-side; user disks are not
overwritten by a dependency update.

To place the private iPhone on a larger drive:

```powershell
.\start.cmd -DataDirectory "D:\My iOS Sweet device"
```

The selected location is remembered in the clone's ignored
`.studio/settings.json`; subsequent launches need only `.\start.cmd`.
Selecting a folder does **not** silently migrate or overwrite a device
elsewhere. Keep your chosen data directory when updating or moving source.

### A fresh clone says the iPhone is already running

An existing emulator can outlive its Studio window. A new clone starts with
its own empty `.studio/data`, which does not mean the earlier iPhone stopped.
Studio now detects this and displays **iPhone running elsewhere** with a
**Connect to running iPhone** button. Use that button instead of downloading
or creating another device.

Reconnection verifies the live process/executable, exact writable overlay,
kernel checksum, local endpoints and authenticated guest instance. It saves
a reference to the existing device in the new workspace; **the iPhone is not
rebooted, cloned, deleted or reinstalled**. Existing apps remain on the same
disk. Any previous device selection in this workspace is backed up before
switching. Keep the original device folder: reconnecting does not move it.

If an emulator cannot be verified, Studio leaves it alone and disables new
device creation. Return to the original Studio window rather than killing
QEMU or deleting `.studio`. If no device exists at all, **Set up iPhone** opens
the normal first-run setup. Reopening a connected Studio loads the existing
app library without starting a second emulator.

## Diagnostics without launching a window

```powershell
.\start.cmd -PrepareOnly
```

This downloads and validates the same dependencies but does not open Studio,
start QEMU, download Apple firmware or touch a physical phone. The bootstrap
returns a nonzero exit code on failure rather than claiming it launched.
Downloads retry; completed verified archives are reused. The launcher rejects
archive path traversal and modified cached binaries before executing them.

If a checksum fails, do not bypass verification. Close Studio, preserve
`.studio/data/`, and rename **only the indicated versioned runtime folder**
before running the command again. Keep the bootstrap log when reporting a
problem. If a managed PC blocks third-party downloads or WebView2 deployment,
an administrator may need to approve those dependencies; the script does not
turn off antivirus, weaken Windows policy, or request a machine-wide install.

## Developers rebuilding every helper

The one-command path uses source-built, precompiled runtime dependencies so
new users do not need an iPhoneOS SDK or Docker. To rebuild those components
yourself, the [complete source-build guide](STUDIO_SOURCE_BUILD.md) is still
available. `desktop/build_runtime_pack.py` constructs the firmware-free ZIP;
`desktop/runtime-lock.json` pins its immutable URL and checksums. The desktop
source itself always runs from the checkout, not from that ZIP.

References for the dependency mechanisms: Python's
[application-local embedded distribution](https://docs.python.org/3/using/windows.html#the-embeddable-package)
and Microsoft's [WebView2 runtime distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).
