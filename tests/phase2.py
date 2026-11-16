#!/usr/bin/env python3
"""Exercise same-key AVB/FEC patching and rejection before the real GSI build."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from image import FS
from verify_apk import sha


def run(args, success=True):
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    if (p.returncode == 0) != success:
        raise RuntimeError(f'Unexpected exit {p.returncode}: {args}\n{p.stdout}{p.stderr}')
    return p.stdout + p.stderr


def main():
    avbtool, key, fec, idmap = [os.environ[n] for n in ['AVBTOOL', 'AVB_SIGNING_KEY', 'FEC', 'IDMAP2']]
    out = ROOT / 'validation/phase2'
    out.mkdir(parents=True, exist_ok=True)
    logs = []
    with tempfile.TemporaryDirectory(dir=ROOT / 'work') as d:
        d = Path(d)
        tree = d / 'tree'
        for p in ['framework', 'etc/selinux', 'system_ext/overlay', 'product/overlay']:
            (tree / p).mkdir(parents=True)
        source_res = d / 'res/values'
        source_res.mkdir(parents=True)
        (source_res / 'arrays.xml').write_text('<resources><string-array name="config_biometric_sensors"><item>0:2:15</item></string-array></resources>')
        manifest = d / 'AndroidManifest.xml'
        manifest.write_text('<manifest package="android"/>')
        aapt = os.environ['AAPT2']
        run([aapt, 'compile', '--dir', d / 'res', '-o', d / 'res.zip'])
        run([aapt, 'link', '-x', '--manifest', manifest, '-o', tree / 'framework/framework-res.apk', d / 'res.zip'])
        (tree / 'etc/selinux/plat_file_contexts').write_text('/system_ext(/.*)? u:object_r:system_file:s0\n/product(/.*)? u:object_r:system_file:s0\n')
        source = d / 'system.img'
        with source.open('wb') as f:
            f.truncate(64 * 1024 * 1024)
        run(['mke2fs', '-q', '-F', '-t', 'ext4', '-d', tree, source])
        fs = FS(source, d)
        fs.setmeta('/system_ext/overlay', 'u:object_r:system_file:s0', True)
        run([sys.executable, avbtool, 'add_hashtree_footer', '--image', source, '--partition_name', 'system',
             '--partition_size', 96 * 1024 * 1024, '--algorithm', 'SHA256_RSA2048', '--key', key,
             '--hash_algorithm', 'sha256', '--salt', '00112233445566778899aabbccddeeff',
             '--rollback_index', '1764547200', '--prop', 'com.android.build.system.os_version:15'])
        baseline = sha(source)
        default_out = d / 'must-not-exist.img'
        failed = run([ROOT / 'patch.sh', '--input', source, '--output', default_out], success=False)
        assert 'AVB footer' in failed and not default_out.exists()
        wrong_key = d / 'wrong-test-key.pem'
        run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', wrong_key])
        wrong_out = d / 'wrong-key-must-not-exist.img'
        failed = run([ROOT / 'patch.sh', '--input', source, '--output', wrong_out, '--idmap2', idmap,
                      '--avbtool', avbtool, '--avb-key', wrong_key, '--fec', fec], success=False)
        assert 'Signing key does not match' in failed and not wrong_out.exists() and sha(source) == baseline
        patched = d / 'patched.img'
        command = [ROOT / 'patch.sh', '--input', source, '--output', patched, '--idmap2', idmap,
                   '--avbtool', avbtool, '--avb-key', key, '--fec', fec]
        logs.append(run(command))
        receipt = json.loads(Path(str(patched) + '.report/receipt.json').read_text())
        assert receipt['avb']['signature_hashtree_fec'] == 'PASS'
        assert receipt['avb']['input']['public_key_sha256'] == receipt['avb']['output']['public_key_sha256']
        assert receipt['avb']['input']['root_digest'] != receipt['avb']['output']['root_digest']
        assert patched.stat().st_size == source.stat().st_size == 96 * 1024 * 1024
        assert sha(source) == baseline
        logs.append(run([ROOT / 'verify.sh', '--image', patched, '--original', source, '--idmap2', idmap,
                         '--require-idmap', '--avbtool', avbtool, '--fec', fec]))
        corrupt = d / 'corrupt.img'
        shutil.copyfile(patched, corrupt)
        with corrupt.open('r+b') as f:
            f.seek(12345); b = f.read(1); f.seek(12345); f.write(bytes([b[0] ^ 1]))
        meta = receipt['avb']['output']
        negative = run([fec, '--verify', '--roots', '2', '--data-size', meta['fec_offset'],
                        '--fec-offset', meta['fec_offset'], '--fec-size', meta['fec_size'], corrupt], success=False)
        assert 'FEC parity mismatch' in negative
        assert sha(source) == baseline
        packed = d / 'system.img.xz'
        logs.append(run([sys.executable, ROOT / 'scripts/compress-verified.py', '--image', patched,
                         '--receipt', str(patched) + '.report/receipt.json', '--output', packed,
                         '--remove-raw-after-check']))
        packed_report = json.loads(Path(str(packed) + '.json').read_text())
        assert packed_report['raw_sha256'] == receipt['output_sha256'] and not patched.exists()
        assert sha(source) == baseline and packed_report['decoded_sha256_and_size'] == 'PASS'
        result = {'same_key_avb_patch': 'PASS', 'signature_hashtree_fec': 'PASS',
                  'default_footer_rejection': 'PASS', 'corruption_rejection': 'PASS',
                  'different_signing_key_rejection': 'PASS',
                  'source_unchanged': True, 'idmap2': receipt['idmap2'], 'fixture_bytes': receipt['bytes'],
                  'xz_ram_staging_and_hash': 'PASS',
                  'is_real_gsi': False}
        (out / 'signed-fixture.json').write_text(json.dumps(result, indent=2) + '\n')
        (out / 'signed-fixture.log').write_text('\n'.join(logs))
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
