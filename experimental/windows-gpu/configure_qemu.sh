#!/usr/bin/env bash
set -euo pipefail
# Invoke inside MSYS2 UCRT64. Both arguments are MSYS paths, not Windows paths.
source_root="${1:?source root required}"
build_dir="${2:?new build directory required}"
source_root="$(cd "$source_root" && pwd)"
export PKG_CONFIG_PATH="$source_root/reims-win-dist/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
test -f "$source_root/reims-win-dist/lib/reims_vgpu_c.dll.lib"
if test -e "$build_dir"; then
    echo 'Choose a new build directory; existing output is preserved.' >&2
    exit 1
fi
mkdir -p "$build_dir"
cd "$build_dir"
"$source_root/qemu-vphone-windows/configure" --target-list=aarch64-softmmu \
    --cc=gcc --cxx=g++ --enable-pvg --enable-png --enable-lzfse --enable-tcg \
    --disable-whpx --disable-hvf --disable-kvm --disable-werror --disable-guest-agent \
    --disable-gtk --disable-sdl --enable-slirp --enable-nettle --disable-opengl \
    --disable-spice --disable-gnutls --disable-curses --disable-vnc --disable-install-blobs
echo 'Configuration finished. Build with ninja -j1 in this directory.'
