#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "$0")/common.sh"
need g++
mkdir -p "$ROOT/work/fec-bin"
args=()
if [[ -n ${FEC_PREFIX:-} ]]; then
    args+=("-I$FEC_PREFIX/usr/include" "$FEC_PREFIX/usr/lib/x86_64-linux-gnu/libfec.a")
else
    args+=(-lfec)
fi
g++ -std=c++17 -O3 -Wall -Wextra -Werror -pthread "$ROOT/tools/fec_raw.cpp" \
    "${args[@]}" -lcrypto -lm -o "$ROOT/work/fec-bin/fec"
printf 'Built raw-image FEC helper: %s\n' "$ROOT/work/fec-bin/fec"
