#!/bin/bash
set -euo pipefail
root=/tmp/studio-appliance
mkdir -p "$root"/{bin,sbin,usr/bin,usr/sbin,usr/lib,usr/share,lib,lib64,dev,proc,sys,tmp,run,etc,tools}
copy() {
  local path="$1"
  test -f "$path"
  mkdir -p "$root$(dirname "$path")"
  cp -L "$path" "$root$path"
}
copy_elf() {
  copy "$1"
  while read -r lib; do test -f "$lib" && copy "$lib"; done < <(ldd "$1" 2>/dev/null | grep -oE '/[^ ]+' | sort -u)
}
copy_elf /bin/busybox
for tool in sh mount umount mkdir mknod sleep sync poweroff cat cp ln; do ln -s busybox "$root/bin/$tool"; done
for tool in /usr/bin/python3 /usr/bin/python3.12 /usr/bin/rsync /usr/local/bin/apfs-fuse /usr/sbin/mkfs.hfsplus /usr/sbin/fsck.hfsplus /usr/sbin/modprobe; do copy_elf "$tool"; done
cp -a /usr/lib/python3.12 "$root/usr/lib/"
find "$root/usr/lib/python3.12" -type d -name __pycache__ -prune -exec rm -rf '{}' +
while read -r module; do
  while read -r lib; do test -f "$lib" && copy "$lib"; done < <(ldd "$module" 2>/dev/null | grep -oE '/[^ ]+' | sort -u)
done < <(find /usr/lib/python3.12 -name '*.so')
kernel=$(basename "$(readlink -f /boot/vmlinuz)" | sed 's/^vmlinuz-//')
mkdir -p "$root/lib/modules/$kernel"
cp /lib/modules/"$kernel"/modules.builtin* "$root/lib/modules/$kernel/"
for module in virtio_pci virtio_blk virtio_scsi hfsplus vfat nls_utf8 nls_cp437 nls_iso8859-1 fuse loop ext4; do
  while read -r _ path _; do
    case "$path" in /*) test -f "$path" && copy "$path";; esac
  done < <(modprobe -S "$kernel" --show-depends "$module" 2>/dev/null || true)
done
while read -r compressed; do zstd -d --rm "$compressed"; done < <(find "$root/lib/modules" -name '*.ko.zst')
depmod -b "$root" "$kernel" 2>/dev/null
cp /src/desktop/appliance/init "$root/init"
cp /src/desktop/appliance/prepare.py "$root/tools/prepare.py"
cp /src/tools/sweet-root-tweaks.py /src/tools/Patch-IosSweet-MGCompat.py "$root/tools/"
chmod 0755 "$root/init"
sed -i 's/\r$//' "$root/init"
printf 'root:x:0:0:root:/root:/bin/sh\n' > "$root/etc/passwd"
printf 'root:x:0:\n' > "$root/etc/group"
cp -L /boot/vmlinuz /out/prepare-kernel
(cd "$root" && find . -print0 | cpio --null -o -H newc 2>/dev/null | gzip -1) > /out/prepare-initrd.gz
mkdir -p /out/licenses
cp /usr/local/share/licenses/apfs-fuse-LICENSE /out/licenses/
cp /usr/share/doc/linux-image-"$kernel"/copyright /out/licenses/linux-copyright 2>/dev/null || true
dpkg-query -W > /out/licenses/appliance-packages.txt
sha256sum /out/prepare-kernel /out/prepare-initrd.gz
echo NATIVE_PREPARER_BUILT
