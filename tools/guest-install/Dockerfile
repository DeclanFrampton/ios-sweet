# Offline filesystem preparation only. The emulator itself stays Windows-native.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LIBGUESTFS_BACKEND=direct LIBGUESTFS_MEMSIZE=512
RUN apt-get update && apt-get install -y --no-install-recommends \
    libguestfs-tools linux-image-generic qemu-utils python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ENTRYPOINT ["guestfish"]
