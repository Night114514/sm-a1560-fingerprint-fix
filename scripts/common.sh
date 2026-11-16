#!/usr/bin/env bash
# Sourced by entry points; never downloads or installs dependencies.
set -euo pipefail
export LC_ALL=C
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export ROOT
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing $1. See README.md dependencies."; }
sdk_tools() {
    local sdk=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}} candidate
    if [[ -n ${BUILD_TOOLS_DIR:-} ]]; then
        candidate=$BUILD_TOOLS_DIR
    elif [[ -n $sdk && -d $sdk/build-tools/35.0.0 ]]; then
        candidate=$sdk/build-tools/35.0.0
    else
        fail 'Set ANDROID_SDK_ROOT (Build Tools 35.0.0) or BUILD_TOOLS_DIR.'
    fi
    export AAPT2=${AAPT2:-$candidate/aapt2}
    export APKSIGNER=${APKSIGNER:-$candidate/apksigner}
    export ZIPALIGN=${ZIPALIGN:-$candidate/zipalign}
    for candidate in "$AAPT2" "$APKSIGNER" "$ZIPALIGN"; do
        [[ -x $candidate ]] || fail "Missing executable: $candidate"
    done
    export ANDROID_JAR=${ANDROID_JAR:-${sdk:+$sdk/platforms/android-35/android.jar}}
    need java
    need python3
}
