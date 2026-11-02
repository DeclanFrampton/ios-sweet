# iOS Sweet: Device registration and IPA installation

**Status (2 November 2026):** a local development bridge has now installed
and launched the supplied `com.iosnova` IPA in an isolated QEMU guest, with
a running process and interactive app screen verified. See
[IPA installation](IPA_INSTALLATION.md). An **Apple-registerable hardware
UDID remains unverified** and is not required by this local signing path.

The new in-guest agent called MobileGestalt directly and received an all-`f`
placeholder. It explicitly reports `udid: null` rather than treating that
placeholder (or its locally generated VM instance ID) as an Apple device ID.

## Check the actual guest identity

From PowerShell on the Windows host:

```powershell
cd D:\Projects\ios-sweet
python tools/probe-ios-device-identity.py --timeout 5
python tools/check-ipa.py 'C:\Users\danho\Downloads\unsigned-candidate-47e40101-091e-42dd-a612-24fd7d7b0fd5.ipa'
```

The first tool opens a temporary **loopback-only** QEMU host forward to guest
TCP 62078 and performs the standard read-only lockdown `QueryType` and
`GetValue(UniqueDeviceID)` requests. The forward is removed in `finally`,
including when the guest does not respond. It never creates a UDID, modifies
an iOS disk, changes any boot setting, uploads a credential or contacts Apple.
If no genuine response is received it reports `udid: null` and exits with
**code 2** so a signing pipeline cannot mistake failure for success.

Live QEMU tests (two repeats) show that the forward can be installed, but
guest lockdown does **not** respond within the bounded timeout. The QEMU
user-network table separately shows established outgoing HTTPS sessions,
so this is not evidence of a generic internet outage. Apple's lockdown
pairing usually requires an Apple USB transport, which this QEMU guest
currently does not emulate. The program cleans up its temporary port.

**Independent live Settings check:** using the running native viewer's
existing swipe/touch controls, opened `Settings → General → About` and
captured a private local screenshot at
`windows-runtime/network-probe/ios-device-about-complete.png`. iOS
reported version **16.7.16**, model **iPhone X**, but both **Serial
Number** and **Model Number** were `N/A`, as was the **Wi-Fi Address**.
That is consistent with the missing MobileGestalt/platform-device identity.
These Settings values do not by themselves constitute a UDID query; the
separate lockdown query was also unresponsive. No third-party app was
installed and no private Apple image was modified during the inspection.

## Why an invented UDID does not solve signing

The original SWEET XNU patch `0025-sweet-builtin-amfi-no-entitlements.patch`
implements `sweet_amfi_get_udid(...)` as `return false`. The later patch
`0035-sweet-amfi-entitlements-platform-binaries.patch` adds XML entitlement
handling; the new guest helper has now verified its app-management
entitlements at runtime. Code signature/page hash checks are retained. The known
MobileGestalt compatibility workaround skips one failing
`MGCopyAnswer(UniqueDeviceID)` call to unblock SpringBoard; it does not
provide an actual consistent device identity. QEMU `virt` exposes VirtIO
network, disk and tablet—not an Apple USB device that Xcode, `usbmuxd` or
`ideviceinstaller` can pair with. A random 40-hex identifier or synthetic
serial is **not proof of Apple device registration**.

Apple's device provisioning documentation:

- https://developer.apple.com/help/account/devices/register-a-single-device
- https://developer.apple.com/documentation/xcode/distributing-your-app-to-registered-devices

## Apple registration versus the demonstrated local installation path

The local bridge, registration and supplied-app launch milestones below
have now been met in the isolated development guest. Hardware identity and
Apple provisioning are separate and remain unverified; the local path must
never be advertised as an Apple-registered device.

1. **Guest identity service:** supply a stable, guest-specific identity
   consistently in MobileGestalt, lockdown and the kernel signing interface;
   confirm its value through the guest service rather than generating one on
   the host. Do not borrow a physical device's identifier.
2. **Signing verification:** confirm an authorised Apple Developer account
   actually accepts the emulated device identity and issues a compatible
   provisioning profile (this is not yet proven or guaranteed). Alternatively
   keep code-signing compatibility *strictly isolated* in a separate local
   development guest and do not call it Apple Ad Hoc provisioning.
3. **Installer transport:** expose an authenticated virtual Apple USB/pairing
   interface and MobileInstallation service, or build a locally restricted
   guest development agent that performs app registration through iOS APIs.
   Merely placing files in `/Applications` does not prove a valid install.
4. **Acceptance test:** safely clone/back up the QCOW2, install a validated
   IPA, check that SpringBoard lists the correct bundle ID, launch the
   process and verify the first screen. Preserve original Apple images.

The original provided `iOSNova` IPA remains **unsigned and unchanged**.
A private copy and its embedded frameworks were locally signed and adjusted
for SWEET's loader, then registered and launched successfully. This is not
proof that a physical-iPhone provisioning profile works in the emulator.

Viewer: http://127.0.0.1:8108/. The guest is not Apple's CoreSimulator;
`xcrun simctl install` cannot target it.
