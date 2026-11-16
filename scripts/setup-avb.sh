#!/usr/bin/env bash
# Optional, explicit online setup for the public AOSP test fixture used by this ROM.
# Never use this fixture to replace a different OEM or production signing key.
set -euo pipefail
# shellcheck source=scripts/common.sh
source "$(dirname -- "$0")/common.sh"
need curl
need python3
need sha256sum
dest=${1:-$ROOT/work/avb-tools}
[[ $# -le 1 && ! -e $dest ]] || fail 'Usage: scripts/setup-avb.sh [new-directory]'
mkdir -p "$ROOT/work"
tmp=$(mktemp -d "$ROOT/work/avb-download.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
base=https://android.googlesource.com/platform/external/avb/+/android-15.0.0_r1
curl -fLsS --retry 2 "$base/avbtool.py?format=TEXT" -o "$tmp/avbtool.b64"
curl -fLsS --retry 2 "$base/test/data/testkey_rsa2048.pem?format=TEXT" -o "$tmp/key.b64"
python3 - "$tmp" <<'PY'
import base64, pathlib, sys
p = pathlib.Path(sys.argv[1])
(p / 'avbtool.py').write_bytes(base64.b64decode((p / 'avbtool.b64').read_bytes()))
(p / 'testkey_rsa2048.pem').write_bytes(base64.b64decode((p / 'key.b64').read_bytes()))
PY
(
    cd "$tmp"
    printf '%s\n' \
        '78a50c8620985709f2e131cf948dcd66ecc43f09ed735e09d75751a7e21e4eb8  avbtool.py' \
        'f1d5765a2bdfb92fb08aee021107c7ac1a7a3f590dafd853771c85375ef0fbd7  testkey_rsa2048.pem' | sha256sum -c -
)
mkdir -p "$dest"
cp -- "$tmp/avbtool.py" "$dest/avbtool.py"
install -m 600 "$tmp/testkey_rsa2048.pem" "$dest/testkey_rsa2048.pem"
printf 'Prepared pinned avbtool and PUBLIC AOSP TEST fixture in %s\n' "$dest"
