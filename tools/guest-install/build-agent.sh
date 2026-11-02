#!/bin/sh
# Run with the existing Linux iOS SDK build image; never needs Apple account keys.
set -eu
mkdir -p /tmp/iossweet-agent-build
/usr/lib/llvm-23/bin/clang -target arm64-apple-ios16.0 -isysroot /opt/apple/sdk \
  -fobjc-arc -Wno-deprecated-declarations -O1 -fuse-ld=lld -Wl,-adhoc_codesign \
  -framework Foundation -framework CoreFoundation -lobjc \
  /src/iossweet-agent.m -o /tmp/iossweet-agent-build/iossweet-agent
cp /tmp/iossweet-agent-build/iossweet-agent /out/iossweet-agent
echo ARM64_IOS_AGENT_BUILD_OK
