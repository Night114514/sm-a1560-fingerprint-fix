#!/usr/bin/env python3
"""Extract the GSI's own idmap2 + runtime libraries for QEMU inspection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile

from image import FS, layout
from verify_apk import require, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--qemu', default='qemu-aarch64')
    a = p.parse_args()
    os.environ['LC_ALL'] = 'C'
    out = Path(a.output).absolute()
    require(not out.exists(), 'Output directory already exists')
    qemu = shutil.which(a.qemu)
    require(qemu and shutil.which('readelf') and shutil.which('debugfs'), 'Need qemu-aarch64, readelf and debugfs')
    out.mkdir(parents=True)
    (out / 'lib64').mkdir()
    records = []
    with tempfile.TemporaryDirectory(dir=out) as scratch:
        scratch = Path(scratch)
        fs = FS(Path(a.image).resolve(), scratch)
        root = layout(fs)
        apex = fs.extract(root + '/apex/com.android.runtime.apex')
        with zipfile.ZipFile(apex) as z:
            require(z.testzip() is None, 'Runtime APEX ZIP is corrupt')
            with z.open('apex_payload.img') as source, (scratch / 'runtime.img').open('wb') as dest:
                shutil.copyfileobj(source, dest)
        (scratch / 'runtime-files').mkdir()
        runtime = FS(scratch / 'runtime.img', scratch / 'runtime-files')
        def copy(source_fs, path, dest):
            shutil.copyfile(source_fs.extract(path), dest)
            dest.chmod(0o755)
            records.append({'image_path': path, 'from_runtime_apex': source_fs is runtime,
                            'file': dest.relative_to(out).as_posix(), 'sha256': sha(dest)})
        copy(runtime, '/bin/linker64', out / 'linker64')
        copy(fs, root + '/bin/idmap2', out / 'idmap2')
        elf = subprocess.check_output(['readelf', '-h', out / 'idmap2'], text=True)
        require('AArch64' in elf, 'Expected ARM64 GSI idmap2')
        pending, seen = [out / 'idmap2'], set()
        while pending:
            current = pending.pop()
            dynamic = subprocess.check_output(['readelf', '-d', current], text=True)
            for name in re.findall(r'NEEDED.*\[([^\]]+)\]', dynamic):
                if name in seen:
                    continue
                require('/' not in name and name.endswith('.so'), 'Unexpected library name')
                seen.add(name)
                dest = out / 'lib64' / name
                path = root + '/lib64/' + name
                i = fs.info(path)
                if i and i['type'] == 'regular':
                    copy(fs, path, dest)
                else:
                    choices = ['/lib64/bionic/' + name, '/lib64/' + name]
                    found = [n for n in choices if runtime.info(n) and runtime.info(n)['type'] == 'regular']
                    require(found, 'Missing runtime library: ' + name)
                    copy(runtime, found[0], dest)
                pending.append(dest)
    wrapper = out / 'idmap2-host'
    wrapper.write_text('#!/bin/sh\n'
                       'runtime_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                       'exec ' + shlex.quote(qemu) + ' -E LD_LIBRARY_PATH="$runtime_dir/lib64" '
                       '"$runtime_dir/linker64" "$runtime_dir/idmap2" "$@"\n')
    wrapper.chmod(0o755)
    (out / 'manifest.json').write_text(json.dumps({'method': 'original Android ARM64 idmap2 under QEMU',
                                                 'image_sha256': sha(a.image), 'qemu_sha256': sha(qemu),
                                                 'files': records}, indent=2) + '\n')
    print(wrapper)


if __name__ == '__main__':
    main()
