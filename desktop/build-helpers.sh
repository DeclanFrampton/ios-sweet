#!/bin/sh
# Development build only; the released application needs no SDK or Docker.
set -eu
clang="${IOS_SWEET_CLANG:-/usr/lib/llvm-23/bin/clang}"
sdk="${IOS_SWEET_SDK:-/opt/apple/sdk}"
test -x "$clang" || { echo "Missing LLVM compiler: $clang" >&2; exit 1; }
test -f "$sdk/SDKSettings.plist" || { echo "Mount your authorised iPhoneOS SDK at $sdk (not a simulator SDK)." >&2; exit 1; }
test -d /out || { echo 'Mount a writable build-output directory at /out.' >&2; exit 1; }
"$clang" -target arm64-apple-ios16.0 -isysroot "$sdk" -fobjc-arc -O1 -Wno-deprecated-declarations -fuse-ld=lld -Wl,-adhoc_codesign -framework Foundation -framework CoreFoundation -lobjc /src/tools/guest-install/iossweet-agent.m -o /out/iossweet-agent
"$clang" -target arm64-apple-ios16.0 -isysroot "$sdk" -O1 -fuse-ld=lld -Wl,-adhoc_codesign -framework CoreFoundation /src/tools/ios-network-seed.c -o /out/iossweet-net-seed
echo STUDIO_GUEST_HELPERS_COMPILED
