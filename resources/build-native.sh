#!/bin/bash
# Runs as root ONLY inside an unprivileged, rootless Podman container.
set -euo pipefail
cd /build
export DEBIAN_FRONTEND=noninteractive
export NINJA_STATUS='[%f/%t] '
phase() { printf 'HFI_BUILD_PHASE %s %s\n' "$1" "$2"; }
phase dependencies 'Installing isolated ARM64 build dependencies...'
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg git python3 \
  ninja-build cmake make pkg-config ccache file \
  libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev \
  libxtst-dev libxkbcommon-dev libwayland-dev wayland-protocols libegl-dev libgles-dev \
  libgl-dev libdrm-dev libgbm-dev libpulse-dev libpipewire-0.3-dev libasound2-dev \
  libudev-dev libdbus-1-dev libdecor-0-dev
# The upstream ARM64 ILP32 guest needs recent LLVM. Use LLVM's signed apt repository.
phase toolchain 'Downloading and installing the LLVM 22 ARM64 compiler...'
curl --fail --silent --show-error --location https://apt.llvm.org/llvm-snapshot.gpg.key \
  -o /build/llvm-archive-key.asc
# Check the primary signing identity published by LLVM before trusting the key.
# A refreshed self-signature/subkey is allowed; a different primary key is not.
llvm_primary_fingerprints=$(gpg --batch --with-colons --show-keys --fingerprint /build/llvm-archive-key.asc | \
  awk -F: '$1 == "pub" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }')
test "$llvm_primary_fingerprints" = '6084F3CF814B57C1CF12EFD515CF4D18AF4F7421'
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
phase configure 'Verifying pinned build-source download safeguards...'
python3 tools/test_build_sources.py
phase configure 'Checking Xbox controls, front-facing VR menus, tutorial, unarmed flashlight, render-rate reticle, stereo sun glow and LAN/online campaign menus...'
python3 tools/test_vr_locomotion.py --cc clang
python3 tools/test_vr_menu.py --cc clang
python3 tools/test_vr_tutorial.py --cc clang
python3 tools/test_vr_tracking.py --cc clang
python3 tools/test_vr_tutorial_buttons.py --cc clang
python3 tools/test_vr_flashlight.py --cc clang
python3 tools/test_vr_sun_glow.py --cc clang
python3 tools/test_vr_projectile_reticle.py --cc clang
python3 tools/test_online_coop_menu.py --cc clang
phase configure 'Configuring the native ARM64 OpenXR game and downloading its build sources...'
python3 configure.py --release --vr --linux-arm64-cc clang
# Record signed-package versions. Security/maintenance updates within Ubuntu
# 22.04 and LLVM22 are intentional; this is not a reproducible-build promise.
dpkg-query -W -f='${Package} ${Version}\n'
export CMAKE_BUILD_PARALLEL_LEVEL=4
export NINJAFLAGS=-j4
phase sdl 'Configuring and compiling SDL3; the native game build follows...'
# The monitor reads SDL's own logs and advances to compile on native Ninja jobs.
ninja -j4 linux_arm64
phase build-check 'Checking the completed native ARM64 VR executable...'
file build/linux_arm64/halo
echo 'Native ARM64 VR build completed.'
