# Public, build-only replacement for the developer's private worker image.
# No Apple SDK is downloaded or copied into this image. Supply an authorised
# iPhoneOS SDK as a read-only mount at /opt/apple/sdk when building helpers.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
ARG LLVM_MAJOR=23
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl --fail --location --retry 3 https://apt.llvm.org/llvm-snapshot.gpg.key \
       | gpg --dearmor -o /usr/share/keyrings/iossweet-llvm.gpg \
    && printf 'deb [signed-by=/usr/share/keyrings/iossweet-llvm.gpg] https://apt.llvm.org/noble/ llvm-toolchain-noble-%s main\n' "$LLVM_MAJOR" \
       > /etc/apt/sources.list.d/iossweet-llvm.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "clang-$LLVM_MAJOR" "lld-$LLVM_MAJOR" python3 file \
    && rm -rf /var/lib/apt/lists/*
ENV IOS_SWEET_CLANG=/usr/lib/llvm-23/bin/clang
WORKDIR /src
CMD ["sh", "/src/desktop/build-helpers.sh"]
