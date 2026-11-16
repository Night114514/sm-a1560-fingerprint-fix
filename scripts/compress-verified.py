#!/usr/bin/env python3
"""Compress a verified derivative with RAM staging, then check the decoded hash.

Linux memfd avoids needing disk space for two raw images plus a compressed image.
The optional cleanup only removes the receipt-matching *derived* raw image after
the complete compressed stream passes CRC and decoded SHA-256/size checks.
"""
import argparse
import fcntl
import hashlib
import json
import lzma
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile

from verify_apk import require, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True)
    p.add_argument('--receipt', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--remove-raw-after-check', action='store_true')
    a = p.parse_args()
    image, output = Path(a.image).resolve(), Path(a.output).absolute()
    receipt = json.loads(Path(a.receipt).read_text())
    require(not output.exists() and not output.is_symlink(), 'Compressed output already exists')
    require(shutil.which('xz') and hasattr(os, 'memfd_create'), 'Need xz and Linux memfd support')
    expected = receipt['output_sha256']
    require(expected != receipt['input_sha256'], 'Only a changed derivative can be packaged/cleaned up')
    require(sha(image) == expected and image.stat().st_size == receipt['bytes'], 'Raw image does not match successful receipt')
    original_stat = image.stat()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.memfd_create('verified-gsi-xz', os.MFD_ALLOW_SEALING)
    temp = None
    try:
        def limit_output():
            # GitHub Release assets must be below 2 GiB; bound anonymous staging too.
            maximum = 2 * 1024**3 - 1
            resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
        result = subprocess.run(['xz', '-T2', '-6', '--check=crc64', '--memlimit-compress=512MiB',
                                 '--stdout', str(image)], stdout=fd, stderr=subprocess.PIPE,
                                preexec_fn=limit_output)
        require(result.returncode == 0, 'xz failed: ' + result.stderr.decode(errors='replace'))
        # Some Python builds omit these constants; values are Linux uapi ABI.
        add_seals, get_seals = getattr(fcntl, 'F_ADD_SEALS', 1033), getattr(fcntl, 'F_GET_SEALS', 1034)
        fcntl.fcntl(fd, add_seals, 0x0f)  # SEAL | SHRINK | GROW | WRITE
        require(fcntl.fcntl(fd, get_seals) & 0x0f == 0x0f, 'RAM staging was not sealed')
        os.lseek(fd, 0, os.SEEK_SET)
        test = subprocess.run(['xz', '--test'], stdin=fd, capture_output=True)
        require(test.returncode == 0, 'xz container CRC check failed')
        os.lseek(fd, 0, os.SEEK_SET)
        decoded_hash, decoded_size = hashlib.sha256(), 0
        with os.fdopen(os.dup(fd), 'rb') as stream, lzma.LZMAFile(stream) as decoded:
            for b in iter(lambda: decoded.read(8 * 1024 * 1024), b''):
                decoded_hash.update(b)
                decoded_size += len(b)
        require(decoded_hash.hexdigest() == expected and decoded_size == receipt['bytes'], 'Decoded XZ differs from verified raw image')
        compressed_hash = hashlib.sha256()
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            b = os.read(fd, 8 * 1024 * 1024)
            if not b:
                break
            compressed_hash.update(b)
        compressed_size = os.fstat(fd).st_size
        if a.remove_raw_after_check:
            current = image.stat()
            require((current.st_dev, current.st_ino, current.st_size) ==
                    (original_stat.st_dev, original_stat.st_ino, original_stat.st_size)
                    and sha(image) == expected, 'Raw derivative changed while compressing; refusing cleanup')
            require(shutil.disk_usage(output.parent).free + current.st_blocks * 512 > compressed_size + 4 * 1024**2,
                    'Insufficient disk space even after derivative cleanup')
            image.unlink()
        else:
            require(shutil.disk_usage(output.parent).free > compressed_size + 4 * 1024**2,
                    'Insufficient disk: use a larger workspace or explicit derivative cleanup option')
        handle, name = tempfile.mkstemp(prefix='.' + output.name + '.', suffix='.partial', dir=output.parent)
        temp = Path(name)
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(handle, 'wb') as dest, os.fdopen(os.dup(fd), 'rb') as source:
            shutil.copyfileobj(source, dest, 8 * 1024 * 1024)
            dest.flush()
            os.fsync(dest.fileno())
        require(sha(temp) == compressed_hash.hexdigest(), 'Disk copy of verified XZ differs from RAM staging')
        os.link(temp, output)
        temp.unlink()
        temp = None
        report = {'file': output.name, 'xz_sha256': compressed_hash.hexdigest(), 'xz_bytes': compressed_size,
                  'raw_sha256': expected, 'raw_bytes': decoded_size, 'xz_test': 'PASS',
                  'decoded_sha256_and_size': 'PASS', 'filter': 'LZMA2 preset 6, 8 MiB dictionary, CRC64',
                  'staging': 'sealed Linux memfd', 'derived_raw_removed_after_check': a.remove_raw_after_check,
                  'original_input': 'UNTOUCHED', 'device_DSU_installation': 'UNTESTED'}
        Path(str(output) + '.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
    finally:
        if temp:
            temp.unlink(missing_ok=True)
        os.close(fd)


if __name__ == '__main__':
    main()
