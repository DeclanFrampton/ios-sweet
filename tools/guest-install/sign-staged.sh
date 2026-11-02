#!/bin/sh
# Run in a fresh local signer container, without keys or network access.
set -eu
test -f /work/payload/Applications/iOSNova.app/Info.plist
mkdir -p /tmp/iossweet-signing/Applications
if [ "${1:-}" = "relocated" ]; then
  test -f /work/relocated-unsigned-app.tar
  tar -xf /work/relocated-unsigned-app.tar -C /tmp/iossweet-signing
else
  cp -a /work/payload/Applications/iOSNova.app /tmp/iossweet-signing/Applications/
fi
cd /tmp/iossweet-signing
python3 - <<'PY'
from pathlib import Path
import plistlib
# Canonical binary Info.plist avoids XML/BOM parsing differences in the
# device's Foundation/LaunchServices. Signatures are produced AFTER this.
for path in Path('Applications/iOSNova.app').rglob('Info.plist'):
    info=plistlib.loads(path.read_bytes())
    path.write_bytes(plistlib.dumps(info,fmt=plistlib.FMT_BINARY))
print('BUNDLE_METADATA_NORMALIZED_BEFORE_SIGNING')
PY
/usr/local/bin/rcodesign sign --timestamp-url none Applications/iOSNova.app
python3 - <<'PY'
from pathlib import Path
import os,stat,struct
root=Path('/tmp/iossweet-signing/Applications/iOSNova.app')
for p in root.rglob('*'):
    if p.is_symlink():
        raise SystemExit('Unexpected symlink in staged development app')
    if p.is_dir():p.chmod(0o755);continue
    with p.open('rb') as f:head=f.read(4)
    macho=head in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xfe\xed\xfa\xcf')
    p.chmod(0o755 if macho else 0o644)
root.chmod(0o755)
print('SIGNED_APP_FILE_MODES_NORMALIZED')
PY
tar --owner=0 --group=0 -cf /work/signed-app.tar Applications/iOSNova.app
echo LOCAL_ADHOC_SIGNING_COMPLETE
