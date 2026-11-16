#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/scripts/common.sh"
sdk_tools
exec python3 "$ROOT/scripts/image.py" patch "$@"
