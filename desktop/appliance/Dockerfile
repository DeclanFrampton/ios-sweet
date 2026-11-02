# Build-time only. End users run the exported kernel/initramfs in native QEMU.
FROM ubuntu:24.04 AS apfs
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git cmake g++ make libfuse3-dev libbz2-dev zlib1g-dev libattr1-dev
RUN git clone https://github.com/sgan81/apfs-fuse.git /src && cd /src && git checkout 66b86bd525e8cb90f9012543be89b1f092b75cf3 && git submodule update --init --recursive && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --parallel 2

# Built by: docker build -t iossweet-offline-disk-tools:local tools/guest-install
FROM iossweet-offline-disk-tools:local
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends busybox-static rsync hfsprogs libfuse3-3 libbz2-1.0 zlib1g python3 && rm -rf /var/lib/apt/lists/*
COPY --from=apfs /src/build/apfs-fuse /usr/local/bin/apfs-fuse
COPY --from=apfs /src/LICENSE /usr/local/share/licenses/apfs-fuse-LICENSE
COPY build.sh /build.sh
ENTRYPOINT ["bash","/build.sh"]
