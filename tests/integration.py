#!/usr/bin/env python3
"""Synthetic fixtures only: no device or real Samsung/Lineage GSI is simulated."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import struct

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from image import FS, config_insert, image_info
from verify_apk import sha


def call(args, ok=True):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if (p.returncode == 0) != ok:
        raise AssertionError(f'Unexpected exit {p.returncode}: {args}\n{p.stdout}{p.stderr}')
    return p.stdout + p.stderr


def main():
    for dep in ['mke2fs', 'debugfs', 'e2fsck']:
        assert shutil.which(dep), f'Missing {dep}'
    base = ROOT / 'work' / 'integration'
    base.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        t = Path(tmp)
        target = t / 'target'
        (target / 'res/values').mkdir(parents=True)
        (target / 'AndroidManifest.xml').write_text('<manifest package="android"/>')
        (target / 'res/values/arrays.xml').write_text('<resources><string-array name="config_biometric_sensors"><item>0:2:15</item></string-array></resources>')
        aapt = os.environ['AAPT2']
        call([aapt, 'compile', '--dir', target / 'res', '-o', t / 'target-res.zip'])
        call([aapt, 'link', '--manifest', target / 'AndroidManifest.xml', '-x',
              '-o', t / 'framework-res.apk', t / 'target-res.zip'])
        competitor = t / 'competitor'
        shutil.copytree(ROOT / 'res', competitor / 'res')
        (competitor / 'res/values/arrays.xml').write_text('<resources><string-array name="config_biometric_sensors"><item>0:2:15</item></string-array></resources>')
        call([aapt, 'compile', '--dir', competitor / 'res', '-o', t / 'competitor-res.zip'])
        def competitor_apk(priority):
            manifest = competitor / 'AndroidManifest.xml'
            manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="example.immutable">'
                                '<uses-sdk android:minSdkVersion="29" android:targetSdkVersion="35"/>'
                                f'<overlay android:targetPackage="android" android:isStatic="true" android:priority="{priority}" '
                                'android:resourcesMap="@xml/overlays"/><application android:hasCode="false"/></manifest>')
            out = t / f'competitor-{priority}.apk'
            call([aapt, 'link', '--manifest', manifest, '-I', os.environ['ANDROID_SDK_ROOT'] + '/platforms/android-35/android.jar',
                  '--auto-add-overlay', '-o', out, t / 'competitor-res.zip'])
            return out
        low_apk, tied_apk = competitor_apk(100), competitor_apk(999)
        for nested, configured in [(False, False), (True, True)]:
            tag = 'nested-configured' if nested else 'flat-static'
            fixture = t / tag
            root = fixture / 'system' if nested else fixture
            for d in ['framework', 'etc/selinux', 'system_ext/overlay/KeepExisting', 'product/overlay']:
                (root / d).mkdir(parents=True)
            shutil.copyfile(t / 'framework-res.apk', root / 'framework/framework-res.apk')
            (root / 'etc/selinux/plat_file_contexts').write_text('/system_ext(/.*)? u:object_r:system_file:s0\n/product(/.*)? u:object_r:system_file:s0\n')
            (root / 'system_ext/overlay/KeepExisting/original.txt').write_text('Do not modify this file.\n')
            shutil.copyfile(low_apk, root / 'system_ext/overlay/KeepExisting/Existing.apk')
            if configured:
                (root / 'system_ext/overlay/config').mkdir()
                (root / 'system_ext/overlay/config/config.xml').write_text(
                    '<?xml version="1.0"?>\n<config>\n<!-- preserve this comment -->\n'
                    '<overlay package="example.immutable" enabled="true" mutable="false"/>\n'
                    '<overlay package="example.mutable" enabled="false" mutable="true"/>\n</config>\n')
            image, out = t / f'{tag}.img', t / f'{tag}-patched.img'
            with image.open('wb') as f:
                f.truncate(64 * 1024 * 1024)
            call(['mke2fs', '-q', '-F', '-t', 'ext4', '-d', fixture, image])
            fs = FS(image, t)
            prefix = '/system' if nested else ''
            for path, _ in fs.tree(prefix + '/system_ext/overlay'):
                i = fs.info(path)
                fs.setmeta(path, 'u:object_r:system_file:s0', i['type'] == 'directory')
            fs.setmeta(prefix + '/system_ext/overlay', 'u:object_r:system_file:s0', True)
            original_hash = sha(image)
            cmd = [ROOT / 'patch.sh', '--input', image, '--output', out, '--allow-unverified-idmap']
            patch_log = call(cmd)
            assert sha(image) == original_hash
            if not configured:
                for kind in ['tie', 'partition-order', 'missing-label']:
                    unsafe = t / f'{kind}.img'; shutil.copyfile(image, unsafe)
                    unsafe_fs = FS(unsafe, t / kind)
                    unsafe_fs.scratch.mkdir()
                    if kind == 'tie':
                        unsafe_fs.cmd('rm "' + prefix + '/system_ext/overlay/KeepExisting/Existing.apk"', True)
                        unsafe_fs.put(tied_apk, prefix + '/system_ext/overlay/KeepExisting/Existing.apk')
                        unsafe_fs.setmeta(prefix + '/system_ext/overlay/KeepExisting/Existing.apk', 'u:object_r:system_file:s0')
                        message = 'Competing dynamic/tied'
                    elif kind == 'partition-order':
                        order = t / 'partition_order.xml'; order.write_text('<partition-order/>')
                        unsafe_fs.put(order, prefix + '/product/overlay/partition_order.xml')
                        message = 'Custom partition_order.xml'
                    else:
                        unsafe_fs.cmd('ea_rm "' + prefix + '/system_ext/overlay" security.selinux', True)
                        message = 'Missing security.selinux'
                    unsafe_hash = sha(unsafe)
                    unsafe_out = t / f'{kind}-output.img'
                    rejected = call([ROOT / 'patch.sh', '--input', unsafe, '--output', unsafe_out, '--allow-unverified-idmap'], ok=False)
                    assert message in rejected, rejected
                    assert not unsafe_out.exists() and sha(unsafe) == unsafe_hash
            verify_log = call([ROOT / 'verify.sh', '--image', out, '--original', image])
            receipt = json.loads(Path(str(out) + '.report/receipt.json').read_text())
            assert receipt['bytes'] == image.stat().st_size == out.stat().st_size
            if configured:
                config = Path(str(out) + '.report/overlay-config.patched.xml').read_text()
                assert '<!-- preserve this comment -->' in config
                assert config.index('example.immutable') < config.index('io.github.sma1560') < config.index('example.mutable')
            failure = call(cmd, ok=False)
            assert 'Output already exists' in failure
            assert sha(image) == original_hash
            # A clean but modified output must be detected by SHA-256 before acceptance.
            corrupt = t / 'corrupt.img'
            shutil.copyfile(out, corrupt)
            with corrupt.open('r+b') as f:
                f.seek(-1, 2); f.write(b'\x01')
            rejected = call([ROOT / 'verify.sh', '--image', corrupt, '--receipt', str(out) + '.report/receipt.json'], ok=False)
            assert 'SHA-256' in rejected
            # Strict mode cannot silently claim idmap success when the tool is absent.
            if not shutil.which('idmap2'):
                strict = t / f'{tag}-strict.img'
                rejected = call([ROOT / 'patch.sh', '--input', image, '--output', strict], ok=False)
                assert 'Native idmap2 verification required' in rejected
                assert not strict.exists()
            results.append({'case': tag, 'input_sha256': original_hash, 'output_sha256': sha(out),
                            'patch': 'PASS', 'readback': 'PASS', 'input_preserved': True,
                            'idmap2': receipt['idmap2'], 'is_real_gsi': False})
            (base / f'{tag}-patch.txt').write_text(patch_log)
            (base / f'{tag}-verify.txt').write_text(verify_log)
        # Guardrails for unsupported layouts, formats, and ambiguous overlay order.
        for data, msg in [(b'\x3a\xff\x26\xed' + b'\0' * 4096, 'sparse'),
                          (b'EROFS' + b'\0' * 4096, 'raw EXT4')]:
            bad = t / 'bad.img'; bad.write_bytes(data)
            try:
                image_info(bad)
                raise AssertionError('Unsupported image accepted')
            except RuntimeError as e:
                assert msg in str(e)
        avb = t / 'avb.img'; shutil.copyfile(image, avb)
        with avb.open('r+b') as f:
            f.seek(-64, 2); f.write(b'AVBf')
        try:
            image_info(avb); raise AssertionError('AVB accepted')
        except RuntimeError as e:
            assert 'AVB' in str(e)
        shared = t / 'shared.img'; shutil.copyfile(image, shared)
        with shared.open('r+b') as f:
            f.seek(1024 + 100); flags = struct.unpack('<I', f.read(4))[0]
            f.seek(1024 + 100); f.write(struct.pack('<I', flags | 0x4000))
        try:
            image_info(shared); raise AssertionError('Shared-blocks feature accepted')
        except RuntimeError as e:
            assert 'shared_blocks' in str(e)
        for data in [b'<config><merge path="other.xml"/></config>',
                     b'<config><overlay package="m"/><overlay package="i" mutable="false"/></config>']:
            try:
                config_insert(data); raise AssertionError('Ambiguous config accepted')
            except RuntimeError:
                pass
        assert b'fingerprintfix' in config_insert(b'<config/>')
    (base / 'result.json').write_text(json.dumps({'cases': results, 'guardrails': 'PASS',
                                                'real_gsi': 'NOT_PROVIDED', 'device': 'UNTESTED'}, indent=2) + '\n')
    print((base / 'result.json').read_text())


if __name__ == '__main__':
    main()
