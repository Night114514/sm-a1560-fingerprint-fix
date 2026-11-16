#!/usr/bin/env python3
"""Inspect compiled APKs, not just source XML. Standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

PACKAGE = 'io.github.sma1560.fingerprintfix'
RESOURCE = 'array/config_biometric_sensors'


def run(args):
    p = subprocess.run([str(a) for a in args], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {args[0]}\n{p.stdout}{p.stderr}')
    return p.stdout + p.stderr


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def aapt(*args):
    return run([os.environ.get('AAPT2', 'aapt2'), *args])


def manifest_attrs(apk):
    tree = aapt('dump', 'xmltree', apk, '--file', 'AndroidManifest.xml')
    attrs = {}
    for line in tree.splitlines():
        m = re.search(r'A: (?:http://schemas.android.com/apk/res/android:)?([\w]+)(?:\(0x[0-9a-f]+\))?=(.*)', line)
        if m:
            value = m[2].split(' (Raw:')[0]
            attrs[m[1]] = value.strip('"')
    return attrs, tree


def verify(apk, report, framework=None, policy='system', idmap2=None, require_idmap=False):
    apk, report = Path(apk).resolve(), Path(report).resolve()
    require(apk.is_file(), f'APK not found: {apk}')
    report.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk) as z:
        require(z.testzip() is None, 'APK ZIP CRC check failed')
        names = z.namelist()
        require(len(names) == len(set(names)), 'Duplicate ZIP entries')
        require(not any(n.endswith('.dex') or n.startswith('lib/') for n in names), 'RRO must contain no code/libraries')
        payload = {n for n in names if not n.startswith('META-INF/') and not n.endswith('/')}
        require(payload == {'AndroidManifest.xml', 'resources.arsc', 'res/xml/overlays.xml'},
                f'Unexpected APK payload: {payload}')
    resources = aapt('dump', 'resources', apk)
    attrs, manifest = manifest_attrs(apk)
    expected = {'package': PACKAGE, 'targetPackage': 'android', 'isStatic': 'true',
                'priority': '999', 'hasCode': 'false', 'minSdkVersion': '29', 'targetSdkVersion': '35'}
    for name, value in expected.items():
        require(attrs.get(name) == value, f'Manifest {name}: expected {value}, got {attrs.get(name)}')
    require('targetName' not in attrs, 'This experiment uses a target without overlayable groups')
    require(len(re.findall(r'E: overlay \(', manifest)) == 1, 'Expected exactly one overlay declaration')
    require(not re.search(r'E: (activity|receiver|provider|service|uses-permission)\b', manifest), 'Unexpected manifest component')
    entries = re.findall(r'\s+resource (0x[0-9a-f]+) (\S+)', resources)
    require({name for _, name in entries} == {RESOURCE, 'xml/overlays'} and len(entries) == 2,
            f'Expected exactly two resource entries: {entries}')
    ids = {name: rid for rid, name in entries}
    require(re.findall(r'\(array\) size=(\d+)', resources) == ['0'],
            'config_biometric_sensors must have one default empty array and no qualifiers')
    require(attrs.get('resourcesMap') == '@' + ids['xml/overlays'], 'Manifest resourcesMap mismatch')
    mapping = aapt('dump', 'xmltree', apk, '--file', 'res/xml/overlays.xml')
    require(len(re.findall(r'E: item \(', mapping)) == 1, 'Expected one explicit resource mapping')
    require(f'A: target="{RESOURCE}"' in mapping and f'A: value=@{ids[RESOURCE]}' in mapping,
            'Compiled resource mapping does not point to the empty array')
    signature = run([os.environ.get('APKSIGNER', 'apksigner'), 'verify', '--verbose', '--print-certs', apk])
    alignment = run([os.environ.get('ZIPALIGN', 'zipalign'), '-c', '-v', '4', apk])
    result = {'apk_sha256': sha(apk), 'package': PACKAGE, 'compiled_array_length': 0,
              'mapping': {RESOURCE: ids[RESOURCE]}, 'signature_verified': True,
              'zip_alignment_verified': True, 'framework': 'NOT_PROVIDED',
              'idmap2': 'NOT_RUN: no actual framework-res.apk or host idmap2',
              'runtime_priority': 'REQUIRES_DEVICE', 'fingerprint_enrollment': 'UNTESTED'}
    for name, value in [('resources.txt', resources), ('manifest.txt', manifest),
                        ('mapping.txt', mapping), ('signature.txt', signature), ('alignment.txt', alignment)]:
        (report / name).write_text(value)
    if framework:
        framework = Path(framework).resolve()
        target = aapt('dump', 'resources', framework)
        target_entries = re.findall(r'\s+resource (0x[0-9a-f]+) (?:android:)?' + re.escape(RESOURCE) + r'\b', target)
        require(len(target_entries) == 1, 'Target framework must contain exactly one config_biometric_sensors entry')
        policy_dump = aapt('dump', 'overlayable', framework)
        (report / 'target-overlayable.txt').write_text(policy_dump)
        # A target declaring any groups requires targetName and per-resource policy checks.
        # This minimal APK intentionally supports the AOSP ungrouped framework only.
        require(not policy_dump.strip(), 'Target declares overlayable groups; inspect policy/targetName before proceeding')
        result.update(framework={'sha256': sha(framework), 'resource_id': target_entries[0],
                                 'overlayable_groups': False, 'fulfilled_partition_policy': policy})
        executable = idmap2 or shutil.which('idmap2')
        if executable:
            idmap_path = report / 'test.idmap'
            idmap_path.unlink(missing_ok=True)
            created = run([executable, 'create', '--target-apk-path', framework,
                           '--overlay-apk-path', apk, '--idmap-path', idmap_path, '--policy', policy])
            dumped = run([executable, 'dump', '--idmap-path', idmap_path])
            (report / 'idmap2-create.txt').write_text(created)
            (report / 'idmap2-dump.txt').write_text(dumped)
            lines = [l for l in dumped.splitlines() if ' -> ' in l and '0x' in l]
            require(len(lines) == 1 and RESOURCE in dumped, 'idmap2 must map exactly the requested array')
            require(target_entries[0] in dumped, 'idmap2 target resource ID mismatch')
            result['idmap2'] = 'PASS (overlayable enforced; one mapping)'
        else:
            result['idmap2'] = 'NOT_RUN: install/build Android 15 host idmap2; logical mapping/policy checked only'
    if require_idmap:
        require(result['idmap2'].startswith('PASS'), 'Native idmap2 verification required but unavailable')
    (report / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apk', default=str(Path(__file__).resolve().parents[1] / 'dist/SmA1560FingerprintFix.apk'))
    p.add_argument('--report', default='work/apk-verification')
    p.add_argument('--framework', help='Actual GSI framework-res.apk, not SDK android.jar')
    p.add_argument('--policy', choices=['product', 'system'], default='system', help='system_ext uses system policy')
    p.add_argument('--idmap2', help='Android 15 Linux host idmap2 executable')
    p.add_argument('--require-idmap', action='store_true')
    a = p.parse_args()
    print(json.dumps(verify(a.apk, a.report, a.framework, a.policy, a.idmap2, a.require_idmap), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, zipfile.BadZipFile) as e:
        sys.exit(f'ERROR: {e}')
