# Third-party IPA installation on native Windows iOS Sweet

**Status (2 November 2026): NOT SUPPORTED / NOT DEMONSTRATED.** The native
Windows QEMU guest is a full iOS-device build running an experimental ARM64
kernel, not Apple's Xcode CoreSimulator. `xcrun simctl install` therefore
does **not** target this guest. Do not claim that copying an `.ipa` file to
the Windows filesystem, starting Safari, or receiving HTTP 200 from the
viewer means the app was installed.

## Safe read-only preflight

Run on the Windows host:

```powershell
cd D:\Projects\ios-sweet
python tools/check-ipa.py 'C:\path\to\your-app.ipa'
```

This validates ZIP integrity and traversal protections, inspects the
`Payload/*.app/Info.plist` bundle identifier, executable ARM64 architecture,
iOS-device Mach-O target, minimum OS version, signature load command,
`_CodeSignature/CodeResources` presence, and embedded provisioning-profile
presence. It reads the supplied IPA **without extracting, copying, signing
or uploading it**. A load command is not evidence that a cryptographic
signature is valid; an archive passing this check is **not proof of device
installation**. `installed_on_guest` always reports `false`.

## Live test performed with the user's supplied unsigned IPA

The 6.59 MB archive is valid and contains one app, **iOSNova**,
`com.iosnova`, minimum iOS 15.1, a 64-bit ARM device executable, with
LC_BUILD_VERSION platform 2 (iOS device). It contains **no** Mach-O
`LC_CODE_SIGNATURE`, `_CodeSignature/CodeResources`, or
`embedded.mobileprovision`. iOS Sweet's current 16.7.16 guest satisfies its
minimum version, but the package is not ready for a normal signed device
installation. No original IPA content was added to Git.

On the running native QEMU guest, `lockdownd` was observed launching. A
temporary QEMU user-network forwarding rule was added **only on host
127.0.0.1** to guest TCP 62078; a read-only lockdown `QueryType` request
received no reply during two bounded attempts (up to 18 seconds). The
forwarding rule was then removed. The host has no `ideviceinstaller`,
`ideviceinfo`, `iproxy` or `ios-deploy` binary, and even if these were
installed, a usable QEMU device pairing/installation transport has not been
established. No package installation or SpringBoard icon was observed.

## Required for future working installation

1. Expose and verify a supported host-to-guest installation transport (for
   example, usable lockdown/mobile installation proxy service via a
   compatible USB or network bridge), or implement a guest install agent
   with explicit integrity and rollback checks. Do not assume `lockdownd`
   appearing in a boot log proves it is reachable.
2. Sign the ARM64 iOS executable and bundle through a valid iOS device
   signing path, with appropriate entitlements and provisioning if required
   by that path; alternatively implement and **verify** a development-only
   unsigned-code path rather than assuming one exists. Do not send keys or
   a private IPA to a remote signer implicitly.
3. Use the guest's actual MobileInstallation/installd registration process,
   confirm the package is installed, then launch it from SpringBoard and
   verify its process and initial screen. Test and preserve a checksum-
   verified clone of the private QCOW2 first.

Until those milestones are complete, **the correct result is that IPA
installation is unproven and this specific unsigned package was not
installed**. The existing GUI and Safari functionality remain separate.
