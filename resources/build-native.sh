#!/bin/bash
# Runs as root ONLY inside an unprivileged, rootless Podman container.
set -euo pipefail
cd /build
export DEBIAN_FRONTEND=noninteractive
echo 'Installing the isolated ARM64 compiler and build dependencies...'
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg git python3 \
  ninja-build cmake make pkg-config ccache file \
  libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev \
  libxtst-dev libxkbcommon-dev libwayland-dev wayland-protocols libegl-dev libgles-dev \
  libgl-dev libdrm-dev libgbm-dev libpulse-dev libpipewire-0.3-dev libasound2-dev \
  libudev-dev libdbus-1-dev libdecor-0-dev
# The upstream ARM64 ILP32 guest needs recent LLVM. Use LLVM's signed apt repository.
curl --fail --silent --show-error --location https://apt.llvm.org/llvm-snapshot.gpg.key \
  -o /build/llvm-archive-key.asc
gpg --batch --yes --dearmor --output /usr/share/keyrings/llvm-archive-keyring.gpg \
  /build/llvm-archive-key.asc
printf '%s\n' 'deb [arch=arm64 signed-by=/usr/share/keyrings/llvm-archive-keyring.gpg] https://apt.llvm.org/jammy/ llvm-toolchain-jammy-22 main' \
  > /etc/apt/sources.list.d/llvm22.list
apt-get update
apt-get install -y --no-install-recommends clang-22 lld-22 llvm-22
for tool in clang ld.lld llvm-ar; do
  ln -sf "/usr/bin/$tool-22" "/usr/local/bin/$tool"
done
clang --version
cd /build/src
python3 configure.py --release --vr --linux-arm64-cc clang
export CMAKE_BUILD_PARALLEL_LEVEL=4
export NINJAFLAGS=-j4
echo 'Building the native Steam Frame OpenXR game. This can take several minutes...'
ninja -j4 linux_arm64
file build/linux_arm64/halo
echo 'Native ARM64 VR build completed.'
