#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/scripts/common.sh"
[[ $# == 0 ]] || fail 'Usage: ./build.sh (configuration uses environment variables; see README.md)'
sdk_tools
[[ -f $ANDROID_JAR ]] || fail 'Missing API 35 android.jar; set ANDROID_JAR or ANDROID_SDK_ROOT.'
need keytool
need sha256sum
mkdir -p "$ROOT/work" "$ROOT/dist"
tmp=$(mktemp -d "$ROOT/work/build.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
ks=${SIGNING_KEYSTORE:-$ROOT/work/experiment.jks}
alias_name=${SIGNING_ALIAS:-experiment}
if [[ -z ${SIGNING_KEYSTORE:-} ]]; then
    # Public experiment password; this is not a production/platform signing key.
    export RRO_KS_PASS=android
    if [[ ! -e $ks ]]; then
        keytool -genkeypair -keystore "$ks" -storepass:env RRO_KS_PASS \
            -keypass:env RRO_KS_PASS -alias "$alias_name" -keyalg RSA -keysize 2048 \
            -validity 3650 -dname 'CN=SM-A1560 RRO Experiment' >&2
    fi
else
    [[ -f $ks && -n ${RRO_KS_PASS:-} ]] || fail 'Custom keystore needs RRO_KS_PASS environment variable.'
fi
"$AAPT2" compile --dir "$ROOT/res" -o "$tmp/resources.zip"
"$AAPT2" link -o "$tmp/unsigned.apk" --manifest "$ROOT/AndroidManifest.xml" \
    -I "$ANDROID_JAR" --auto-add-overlay --no-resource-deduping --no-resource-removal \
    "$tmp/resources.zip"
"$ZIPALIGN" -f -p 4 "$tmp/unsigned.apk" "$tmp/aligned.apk"
"$APKSIGNER" sign --ks "$ks" --ks-key-alias "$alias_name" --ks-pass env:RRO_KS_PASS \
    --key-pass env:RRO_KS_PASS --v1-signing-enabled true --v2-signing-enabled true \
    --v3-signing-enabled true --v4-signing-enabled false \
    --out "$tmp/SmA1560FingerprintFix.apk" "$tmp/aligned.apk"
"$ROOT/verify.sh" --apk "$tmp/SmA1560FingerprintFix.apk" --report "$tmp/verification"
mv -- "$tmp/SmA1560FingerprintFix.apk" "$ROOT/dist/SmA1560FingerprintFix.apk"
rm -rf -- "$ROOT/dist/apk-verification"
mv -- "$tmp/verification" "$ROOT/dist/apk-verification"
(cd "$ROOT/dist" && sha256sum SmA1560FingerprintFix.apk > SmA1560FingerprintFix.apk.sha256)
cat "$ROOT/dist/SmA1560FingerprintFix.apk.sha256"
printf 'Built and checked the RRO APK. Device fingerprint enrollment is UNTESTED.\n'
