#!/usr/bin/env python3
"""Opt-in AVB system-footer rebuild with the *same* signing key and policy.

Never edits a device vbmeta/boot/vendor partition or creates a vbmeta.img.
Only the SHA256_RSA2048, SHA-256, 4096-byte, two-root FEC layout verified in
the phase-2 baseline is supported. Other layouts stop before any copy edits.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from verify_apk import require


def prefix_sha(path, size):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while size:
            b = f.read(min(size, 8 * 1024 * 1024))
            require(b, 'Truncated AVB data image')
            h.update(b)
            size -= len(b)
    return h.hexdigest()


class AvbSupport:
    def __init__(self, tool, key, fec, image, report, data_bytes):
        self.tool, self.key = Path(tool).resolve(), Path(key).resolve() if key else None
        self.fec, self.report = Path(fec).resolve(), Path(report).resolve()
        require(self.tool.is_file() and self.fec.is_file() and self.fec.name == 'fec',
                'AVB mode requires avbtool.py and a verified executable named fec')
        require(os.access(self.fec, os.X_OK), 'FEC helper is not executable')
        self.report.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, 'PATH': str(self.fec.parent) + os.pathsep + os.environ['PATH']}
        spec = importlib.util.spec_from_file_location('phase2_avbtool', self.tool)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.metadata, self.public_key = self.inspect(image)
        require(self.metadata['data_bytes'] == data_bytes, 'AVB image size differs from EXT4 geometry')
        if self.key:
            public = self.report / 'signing-public-key.avbpubkey'
            self.call(['extract_public_key', '--key', self.key, '--output', public], 'public-key.txt')
            require(public.read_bytes() == self.public_key,
                    'Signing key does not match original embedded AVB key; refusing a trust change')
        self.verify(image, 'input')
        (self.report / 'input-metadata.json').write_text(json.dumps(self.metadata, indent=2) + '\n')

    def call(self, args, log):
        p = subprocess.run([sys.executable, str(self.tool), *map(str, args)],
                           capture_output=True, text=True, env=self.env)
        (self.report / log).write_text(p.stdout + p.stderr)
        require(p.returncode == 0, f'AVB command failed; see {self.report / log}')
        return p.stdout + p.stderr

    def inspect(self, path):
        m = self.module
        image = m.ImageHandler(str(path), read_only=True)
        footer, header, descriptors, image_size = m.Avb()._parse_image(image)
        require(footer and header.algorithm_type == 1 and header.flags == 0,
                'Only a signed SHA256_RSA2048 footer with flags=0 is supported')
        require(header.public_key_metadata_size == 0 and header.rollback_index_location == 0,
                'Unsupported AVB key metadata or rollback index location')
        trees = [d for d in descriptors if isinstance(d, m.AvbHashtreeDescriptor)]
        props = [d for d in descriptors if isinstance(d, m.AvbPropertyDescriptor)]
        require(len(trees) == 1 and len(trees) + len(props) == len(descriptors),
                'Unsupported AVB descriptors; expected one hashtree plus properties')
        t = trees[0]
        require(t.partition_name == 'system' and t.hash_algorithm == 'sha256' and t.flags == 0
                and t.dm_verity_version == 1 and t.data_block_size == t.hash_block_size == 4096
                and t.fec_num_roots == 2, 'Unsupported hashtree/FEC geometry or flags')
        require(t.image_size == footer.original_image_size == t.tree_offset
                and t.tree_offset + t.tree_size == t.fec_offset
                and t.fec_offset + t.fec_size <= footer.vbmeta_offset,
                'Non-contiguous or invalid AVB geometry')
        image.seek(footer.vbmeta_offset + header.SIZE + header.authentication_data_block_size + header.public_key_offset)
        public_key = image.read(header.public_key_size)
        properties = [[p.key, p.value.decode('utf-8')] for p in props]
        require(len({k for k, _ in properties}) == len(properties), 'Duplicate AVB properties')
        metadata = {'algorithm': 'SHA256_RSA2048', 'public_key_sha256': hashlib.sha256(public_key).hexdigest(),
                    'public_key_sha1': hashlib.sha1(public_key).hexdigest(), 'image_bytes': image_size,
                    'data_bytes': t.image_size, 'partition_name': t.partition_name,
                    'hash_algorithm': t.hash_algorithm, 'block_size': t.data_block_size,
                    'tree_offset': t.tree_offset, 'tree_size': t.tree_size, 'fec_num_roots': t.fec_num_roots,
                    'fec_offset': t.fec_offset, 'fec_size': t.fec_size, 'salt': t.salt.hex(),
                    'root_digest': t.root_digest.hex(), 'rollback_index': header.rollback_index,
                    'rollback_index_location': header.rollback_index_location, 'flags': header.flags,
                    'release_string': header.release_string, 'properties': properties}
        # ImageHandler owns a regular read-only file; close it without retaining descriptors.
        image._image.close()
        return metadata, public_key

    def verify(self, image, label):
        metadata, public_key = self.inspect(image)
        require(public_key == self.public_key, 'Output AVB public key changed')
        # avbtool resolves the hashtree partition as <directory>/system.img.
        # A private temporary symlink supplies that basename; it is never committed.
        with tempfile.TemporaryDirectory(prefix='verify-', dir=self.report) as d:
            alias = Path(d) / 'system.img'
            alias.symlink_to(Path(image).resolve())
            args = ['verify_image', '--image', alias]
            if self.key:
                args += ['--key', self.key]
            self.call(args, label + '-signature-hashtree.txt')
        p = subprocess.run([str(self.fec), '--verify', '--roots', str(metadata['fec_num_roots']),
                            '--data-size', str(metadata['fec_offset']), '--fec-offset', str(metadata['fec_offset']),
                            '--fec-size', str(metadata['fec_size']), str(image)], capture_output=True, text=True)
        (self.report / (label + '-fec.txt')).write_text(p.stdout + p.stderr)
        require(p.returncode == 0, f'AVB FEC comparison failed; see {label}-fec.txt')
        return metadata

    def prepare_copy(self, image):
        require(self.key, 'Signing key required for AVB rebuild')
        self.call(['erase_footer', '--image', image], 'erase-copy-footer.txt')
        require(Path(image).stat().st_size == self.metadata['data_bytes'], 'AVB erase did not produce expected EXT4 length')

    def rebuild(self, image):
        require(self.key, 'Signing key required for AVB rebuild')
        before = prefix_sha(image, self.metadata['data_bytes'])
        d = self.metadata
        args = ['add_hashtree_footer', '--image', image, '--partition_size', d['image_bytes'],
                '--partition_name', d['partition_name'], '--algorithm', d['algorithm'], '--key', self.key,
                '--hash_algorithm', d['hash_algorithm'], '--block_size', d['block_size'], '--salt', d['salt'],
                '--fec_num_roots', d['fec_num_roots'], '--rollback_index', d['rollback_index'],
                '--rollback_index_location', d['rollback_index_location'], '--flags', d['flags'],
                '--internal_release_string', d['release_string']]
        for k, v in d['properties']:
            args += ['--prop', k + ':' + v]
        self.call(args, 'rebuild-system-footer.txt')
        require(prefix_sha(image, d['data_bytes']) == before, 'AVB rebuild altered checked EXT4 bytes')
        after = self.verify(image, 'output')
        for key in d:
            if key != 'root_digest':
                require(after[key] == d[key], f'AVB field changed unexpectedly: {key}')
        require(after['root_digest'] != d['root_digest'], 'Modified EXT4 must have a new root digest')
        result = {'input': d, 'output': after, 'patched_ext4_sha256': before,
                  'signature_hashtree_fec': 'PASS', 'device_vbmeta_partition': 'UNTOUCHED'}
        (self.report / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
