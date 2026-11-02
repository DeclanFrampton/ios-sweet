# Isolated local iOS Sweet app-install experiment

This is a **local development** bridge for the private native-Windows QEMU
guest, not Apple device registration, App Store signing, or a public signing
service. The user's original IPA, Apple root disk and baseline QCOW2 must
remain unchanged. The initial acceptance target is the supplied `com.iosnova`
IPA. Arbitrary executables, shell commands and other app paths are rejected.

## Components

- `iossweet-agent.m`: an ARM64 iOS process inside the test guest, launched by
  a new launchd job. It reads the guest's actual MobileGestalt answer, reads
  the fixed staged bundle, creates its own app-data container via iOS APIs,
  registers that bundle with LaunchServices, requests a launch and checks
  for the matching guest process. The agent does not impersonate Apple or
  generate an Apple UDID.
- `client.py`: host-to-guest communication through a temporary **loopback**
  QEMU network forward. Requests carry a private 256-bit capability in the
  Authorization header, never the URL. Temporary forwarding is removed on
  success, timeout and failure.
- `server.py` / `panel.html`: localhost-only control page. The guest token
  stays server-side. Writes require exact local Host/Origin plus a request
  nonce. No generic shell or path arguments are exposed.
- `build-agent.sh`, `sign-agent.sh`, `sign-staged.sh`: cross-compile and
  locally ad-hoc-sign the helper/app in ephemeral containers, without Apple
  keys or external network access. All generated binaries and private
  configuration remain under ignored `windows-runtime/`.
- `make-agent-payload.py`: preserve every existing consolidated launchd job
  and add one explicitly identified test helper. The token file is mode
  0600, its directory 0700. No other service's memory limits are altered.
- `relocate-frameworks.py`: optional private-copy compatibility step for
  SWEET's loader. Rewrite only relative references to libraries actually
  embedded in the selected bundle to their fixed test-guest location,
  then re-sign the complete app. Apple system files are not patched.

## Runtime protections and observed findings

The guest bridge listens on **10.0.2.15:49160**, accepts only the QEMU NAT
host or loopback, limits headers/concurrent clients, checks the capability
and rejects browser Origin headers. The host control page binds only
**127.0.0.1**. The helper has explicit *local development* app-management
entitlements; these are not an Apple-issued signature and must not be used
as credentials for a physical iPhone.

Live testing found that the guest initially assigned the helper a **6 MiB**
per-process memory limit. Loading app-management frameworks exceeded that
limit and caused a real jetsam kill. The helper now sets and reports a
bounded **256 MiB limit for itself only**; global jetsam remains enabled.

MobileGestalt returned an all-`f` placeholder instead of a meaningful UDID.
The helper reports `udid: null` for placeholder values. The `vmInstanceId`
is a locally generated test-instance identifier and is **not an Apple UDID**.

The V5 test guest successfully registered `com.iosnova` at
`/Applications/iOSNova.app` using `registerApplicationDictionary:`. Launch
reached the actual executable but dyld reported that security policy refused
the embedded React framework's `@rpath` expansion. The next test bundle
uses explicit paths to its four packaged Mach-O images and is re-signed
afterward. **The V6 live test passed**: iOS registered the bundle, accepted
its launch, reported executable PID 324 and rendered the supplied app's
Simple sign-in form. A real touch switched it to the Create account form;
the same process remained alive. The host panel also relaunched it from
Home. No user account was submitted. Registration alone was not used as
proof of screen rendering.
The same installed QCOW2 was then checkpointed, stopped and restarted by
the user-facing Apps launcher; iOS retained its `com.iosnova` registration
without running the installation procedure again. It launched as new PID
239 and rendered the Simple sign-in form again after that restart.

## Local commands

The config file is a **private** generated file, never a repository asset.
Example (replace the work directory with the actual prepared test instance):

```powershell
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json status
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json identity
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json staged
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json register
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json apps
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json launch
python tools/guest-install/client.py --config windows-runtime/experiments/TEST/host-bridge.json processes
python tools/guest-install/server.py --config windows-runtime/experiments/TEST/host-bridge.json --port 8109
```

**Do not run the filesystem preparation container against the live guest or
the original raw disk writable.** Create a new QCOW2 over the read-only
clean base, mount only that offline test copy, add the generated payload,
cleanly unmount it, restore its correct Windows backing-file path and run
only one native iOS guest. Preserve a verified baseline backup first.

An API timeout can leave the guest's registration call still pending. Check
`status.operationPhase` and `apps` before reissuing it or declaring failure.
Only a registered bundle, running process **and a visible app screen** satisfy
the full install-and-launch acceptance test.
