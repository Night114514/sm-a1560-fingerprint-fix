#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/scripts/common.sh"
if [[ ${1:-} == --image ]]; then
    shift
    sdk_tools
    exec python3 "$ROOT/scripts/image.py" verify "$@"
fi
sdk_tools
exec python3 "$ROOT/scripts/verify_apk.py" "$@"
