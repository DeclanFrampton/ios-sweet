# IPA installation on native Windows iOS Sweet

## Verified local development installation — 2 November 2026

The supplied unsigned IPA (`com.iosnova`, ARM64 iOS-device build, minimum
iOS 15.1) has passed a real install-and-launch test in an **isolated** iOS
Sweet QEMU guest. The exact app content displays the **Simple** sign-in form;
tapping **Create account** changes it to the name/email/password form.
No account was submitted or created during the UI test.

Acceptance evidence from the guest:

- LaunchServices reports `com.iosnova` registered at `/Applications/iOSNova.app`.
- The guest accepted `openApplicationWithBundleID:` and reported a running
  `/Applications/iOSNova.app/iOSNova` process (PID 324 in the first successful run).
- The framebuffer visibly showed the app's sign-in screen, then its Create
  account screen after a real touch input.
- The localhost browser panel also successfully requested a launch and
  confirmed the live app process. HTTP 200 alone was not used as proof.
- After a clean stop and restart through the new app launcher, LaunchServices
  still reported the same registered bundle **without reinstalling it**.
  A subsequent launch ran the executable as new PID 239 and visibly rendered
  the Simple sign-in form again, confirming persistence across a full restart.

## Open the tested app on the prepared Windows host

Double-click **iOS Sweet Apps** on the desktop, or run
`Start-iOS-Sweet-Apps.cmd` from the repository. The machine-local manifest
selects the tested private overlay and pinned kernel. The launcher reuses a
matching current guest and refuses to replace an unrelated one.

- App controls: `http://127.0.0.1:8109/`
- Emulated iPhone screen: `http://127.0.0.1:8108/`

On the control page, **Check registration**, **Launch iOSNova**, and
**Check running process** query the actual iOS guest. The guest takes time
to boot under software emulation; an early connection failure is not proof
that the prepared app is absent. Only one native iOS QEMU is started.

Fresh clones do not include the private app-test manifest, Apple filesystem,
test IPA, capability token or compiled helper. The public repository
contains source, validators and build/preparation scripts only.

## What made this work

The provided IPA was genuinely unsigned. A separate private copy was
ad-hoc-signed locally, including its embedded React, ReactNativeDependencies
and Hermes frameworks. Its Info.plists were canonicalised to binary format
before signing. No Apple Developer private key or physical-device UDID was
required or sent to any remote service.

The guest's dyld initially terminated the app with `security policy does not
allow @ path expansion` for the React framework. The isolated app copy was
therefore adjusted to reference its own embedded libraries at their exact
test-guest paths, and the whole bundle was re-signed. **System dyld, the
kernel and global signature enforcement were not changed for this fix.**
The resulting relocated bundle is QEMU-test-specific, not a package to
distribute to a normal physical iPhone.

A dedicated guest helper invokes MobileContainerManager and LaunchServices
for this one fixed bundle. Its local development signature carries explicit
app-management permissions, verified at runtime. Its own per-process limit
was raised from the guest's observed 6 MiB to a bounded 256 MiB to avoid the
helper being killed while loading frameworks. Other processes' limits and
global jetsam policy are unchanged.

## Identity and signing distinction

The helper's actual `MGCopyAnswer(UniqueDeviceID)` query returned an all-`f`
placeholder. It reports that as **`udid: null`**, not a valid Apple UDID.
Its persistent `vmInstanceId` is a local identifier only. This test does not
establish Apple Developer registration, physical-device provisioning, an
Apple device certificate or a working USB lockdown transport.

Local development signing is sufficient for this prepared, custom-kernel
test environment. It is **not** equivalent to Apple Ad Hoc distribution.
The original IPA remains unchanged; other IPAs and additional permissions
still require their own compatibility and acceptance tests.

## Safety, rollback and reproducibility

The working base image and baseline single/two-core overlays were preserved.
All app installation changes are confined to a separate QCOW2 over the
read-only base. A checksum-verified pre-change backup and a checkpoint of
the successfully installed guest are kept under ignored
`windows-runtime/backups/`.

For the ordinary baseline guest, cleanly stop the app test using
`tools/Start-IosSweet-Windows.ps1 -Stop`, then use the original
`Start-iOS-Sweet-Windows.cmd`. Do not run two iOS guests simultaneously or
mount a running guest disk writable.

The guest agent is capability-protected and restricted to the QEMU private
network. Its host control page is loopback-only, checks Origin/Host and a
request nonce, and never exposes the private guest token to browser code.
No generic shell, arbitrary executable path or public installer endpoint
is available. See [implementation notes](../tools/guest-install/README.md).

The existing `python tools/check-ipa.py "C:\path\app.ipa"` command is a
read-only package preflight, **not** an installer or proof of installation.
