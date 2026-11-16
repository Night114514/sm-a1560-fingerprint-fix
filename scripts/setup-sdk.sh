#!/usr/bin/env bash
# Optional online tool setup; build.sh itself works offline.
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "$0")/common.sh"
need curl
need unzip
need sha256sum
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'These SDK archives require x86_64 Linux.'
sdk=${1:-$ROOT/work/android-sdk}
[[ $# -le 1 ]] || fail 'Usage: scripts/setup-sdk.sh [new-sdk-directory]'
[[ ! -e $sdk ]] || fail 'SDK destination exists; choose a new directory or use the existing SDK.'
mkdir -p "$ROOT/work"
tmp=$(mktemp -d "$ROOT/work/sdk-download.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
curl -fL --retry 2 --connect-timeout 20 --max-time 600 \
    https://dl.google.com/android/repository/build-tools_r35_linux.zip -o "$tmp/build-tools.zip"
curl -fL --retry 2 --connect-timeout 20 --max-time 600 \
    https://dl.google.com/android/repository/platform-35_r02.zip -o "$tmp/platform.zip"
(
    cd "$tmp"
    printf '%s\n' \
        'bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88  build-tools.zip' \
        '0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0  platform.zip' | sha256sum -c -
)
mkdir -p "$sdk/build-tools" "$sdk/platforms"
unzip -q "$tmp/build-tools.zip" -d "$sdk/build-tools"
mv -- "$sdk/build-tools/android-15" "$sdk/build-tools/35.0.0"
unzip -q "$tmp/platform.zip" -d "$sdk/platforms"
"$sdk/build-tools/35.0.0/aapt2" version
printf 'SDK prepared at: %s\nSet ANDROID_SDK_ROOT to this directory before building.\n' "$sdk"
