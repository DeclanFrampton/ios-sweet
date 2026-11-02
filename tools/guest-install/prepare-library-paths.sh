#!/bin/sh
set -eu
mkdir -p /tmp/iossweet-library-paths/Applications
cp -a /work/payload/Applications/iOSNova.app /tmp/iossweet-library-paths/Applications/
python3 /scripts/relocate-frameworks.py /tmp/iossweet-library-paths/Applications/iOSNova.app
tar --owner=0 --group=0 -C /tmp/iossweet-library-paths \
  -cf /work/relocated-unsigned-app.tar Applications/iOSNova.app
echo PRIVATE_APP_LIBRARY_PATHS_PREPARED_REQUIRES_RESIGNING
