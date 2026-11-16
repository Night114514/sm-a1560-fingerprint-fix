#!/usr/bin/env python3
"""Transport an already verified image; refuse every other input/output hash."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from verify_apk import require, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--output')
    p.add_argument('--delta', required=True)
    p.add_argument('--metadata', required=True)
    p.add_argument('--verify-only', action='store_true')
    a = p.parse_args()
    source, delta = Path(a.input).resolve(), Path(a.delta).resolve()
    m = json.loads(Path(a.metadata).read_text())
    require(m['format'] == 'SMGSID1' and m['block_bytes'] == 4096, 'Unsupported delta format')
    require(source.stat().st_size == m['bytes'] and sha(source) == m['input_sha256'], 'Original image hash/size mismatch')
    require(sha(delta) == m['delta_sha256'], 'Delta transport hash mismatch')
    records, end = [], 0
    with gzip.open(delta, 'rb') as f:
        require(f.read(8) == b'SMGSID1\n', 'Invalid delta header')
        while True:
            b = f.read(12)
            require(len(b) == 12, 'Truncated delta')
            offset, size = struct.unpack('<QI', b)
            if offset == 2**64 - 1:
                require(size == 0 and not f.read(1), 'Invalid delta terminator')
                break
            require(0 < size <= 4096 and offset % 4096 == 0 and offset >= end
                    and offset + size <= m['bytes'], 'Invalid delta range')
            data = f.read(size)
            require(len(data) == size, 'Truncated delta block')
            records.append((offset, data))
            end = offset + size
        require(len(records) == m['changed_blocks'], 'Delta block count mismatch')
    if a.verify_only:
        target = hashlib.sha256()
        with source.open('rb') as f:
            for offset, data in records:
                remaining = offset - f.tell()
                while remaining:
                    b = f.read(min(remaining, 8 * 1024 * 1024))
                    require(b, 'Truncated original')
                    target.update(b)
                    remaining -= len(b)
                f.seek(len(data), 1)
                target.update(data)
            for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
                target.update(b)
        require(target.hexdigest() == m['output_sha256'], 'Reconstructed stream differs from verified image')
        print('Reconstructed stream matches verified image:', target.hexdigest())
        return
    require(a.output, 'Specify --output or --verify-only')
    output = Path(a.output).absolute()
    require(not output.exists() and not output.is_symlink(), 'Output already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + output.name + '.', dir=output.parent)
    os.close(fd)
    temp = Path(name)
    try:
        subprocess.run(['cp', '--sparse=always', '--reflink=auto', '--', str(source), str(temp)], check=True)
        os.chmod(temp, 0o600)
        with temp.open('r+b') as f:
            for offset, data in records:
                f.seek(offset)
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
        require(temp.stat().st_size == m['bytes'] and sha(temp) == m['output_sha256'], 'Reconstructed image hash mismatch')
        require(sha(source) == m['input_sha256'], 'Original input changed')
        os.link(temp, output)
        print('Reconstructed verified image:', m['output_sha256'])
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
