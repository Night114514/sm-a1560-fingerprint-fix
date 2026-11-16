#!/usr/bin/env python3
"""Conservative, mount-free EXT4 patcher. Never writes the source image."""
import argparse
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.parsers import expat

from verify_apk import PACKAGE, RESOURCE, aapt, manifest_attrs, require, run, sha, verify as verify_apk

APK_NAME = 'SmA1560FingerprintFix.apk'


def q(value):
    s = str(value)
    require(not any(c in s for c in '\n\r\x00"\\'), f'Unsupported character in debugfs path: {s!r}')
    return '"' + s + '"'


def tools():
    for t in ['debugfs', 'e2fsck', 'cp']:
        require(shutil.which(t), f'Missing {t}; see README.md dependencies')


def image_info(path):
    require(path.is_file(), f'Not a regular image: {path}')
    size = path.stat().st_size
    with path.open('rb') as f:
        magic = f.read(4)
        require(magic != b'\x3a\xff\x26\xed', 'Android sparse image: convert a COPY using simg2img first')
        if size >= 64:
            f.seek(-64, 2)
            require(f.read(4) != b'AVBf', 'AVB footer detected. No automatic AVB/vbmeta changes are permitted')
        f.seek(1024)
        sb = f.read(1024)
    require(len(sb) == 1024 and sb[56:58] == b'\x53\xef', 'Expected raw EXT4 (not EROFS/super/compressed image)')
    u32 = lambda offset: struct.unpack_from('<I', sb, offset)[0]
    incompat, rocompat = u32(96), u32(100)
    require(incompat & 0x40, 'EXT4 extents feature required')
    require(not incompat & (0x4 | 0x10000), 'Journal recovery or encryption feature present; refusing offline patch')
    require(not rocompat & (0x1000 | 0x4000), 'Read-only/shared_blocks EXT4 unsupported; prepare a separate writable copy first')
    require(struct.unpack_from('<H', sb, 58)[0] & 1, 'Filesystem not cleanly unmounted')
    block_size = 1024 << u32(24)
    blocks = u32(4) | ((u32(336) << 32) if incompat & 0x80 else 0)
    free = u32(12) | ((u32(344) << 32) if incompat & 0x80 else 0)
    require(size == blocks * block_size, 'Image has an unexplained trailer/padding or is truncated; inspect before patching')
    # Refuse visible loop-device attachments; no mounting is performed by this project.
    for f in Path('/sys/block').glob('loop*/loop/backing_file'):
        try:
            backing = f.read_text().strip()
            require(not backing or Path('/' + backing.lstrip('/')).resolve() != path.resolve(),
                    'Image is attached to a loop device; detach/unmount it first')
        except PermissionError:
            pass
    return {'bytes': size, 'block_size': block_size, 'blocks': blocks, 'free_bytes': free * block_size,
            'incompat': hex(incompat), 'ro_compat': hex(rocompat)}


def fsck(image, log):
    p = subprocess.run(['e2fsck', '-f', '-n', str(image)], capture_output=True, text=True,
                       env={**os.environ, 'LC_ALL': 'C'})
    Path(log).write_text(p.stdout + p.stderr)
    require(p.returncode == 0, f'e2fsck -fn failed ({p.returncode}); see {log}. No automatic -y repair')


class FS:
    def __init__(self, image, scratch):
        self.image, self.scratch = Path(image), Path(scratch)
        self.counter = 0

    def cmd(self, command, write=False):
        args = ['debugfs'] + (['-w'] if write else []) + ['-R', command, str(self.image)]
        return run(args)

    def tmp(self, prefix='extract'):
        self.counter += 1
        return self.scratch / f'{prefix}-{self.counter}'

    def info(self, path):
        text = self.cmd('stat ' + q(path))
        m = re.search(r'Inode:\s*(\d+)\s+Type:\s*(\w+)\s+Mode:\s*(\d+)', text)
        if not m:
            return None
        owner = re.search(r'User:\s*(\d+)\s+Group:\s*(\d+)', text)
        return {'inode': int(m[1]), 'type': m[2], 'mode': m[3],
                'uid': int(owner[1]), 'gid': int(owner[2])}

    def exists(self, path):
        return self.info(path) is not None

    def directory(self, path):
        i = self.info(path)
        return i is not None and i['type'] == 'directory'

    def extract(self, path):
        i = self.info(path)
        require(i and i['type'] == 'regular', f'Required regular file missing or symlink: {path}')
        out = self.tmp()
        self.cmd('dump ' + q(path) + ' ' + q(out))
        require(out.is_file(), f'debugfs dump failed: {path}')
        return out

    def children(self, path):
        result = []
        for line in self.cmd('ls -p ' + q(path)).splitlines():
            fields = line.split('/')
            if len(fields) >= 7 and fields[1].isdigit() and fields[5] not in ('.', '..', ''):
                result.append((path.rstrip('/') + '/' + fields[5], int(fields[2], 8)))
        return result

    def tree(self, path):
        if not self.directory(path):
            return []
        result = []
        for child, mode in self.children(path):
            require(not stat.S_ISLNK(mode), f'Overlay subtree contains symlink; manual review required: {child}')
            result.append((child, mode))
            if stat.S_ISDIR(mode):
                result.extend(self.tree(child))
        return result

    def label(self, path):
        out = self.tmp('label')
        self.cmd('ea_get -f ' + q(out) + ' ' + q(path) + ' security.selinux')
        require(out.exists() and out.stat().st_size, f'Missing security.selinux xattr: {path}')
        return out.read_bytes().rstrip(b'\0').decode('ascii')

    def put(self, source, dest):
        require(not self.exists(dest), f'Refusing to overwrite {dest}')
        self.cmd('write ' + q(source) + ' ' + q(dest), True)
        require(sha(self.extract(dest)) == sha(source), f'Write/read-back mismatch: {dest}')

    def setmeta(self, path, label, directory=False):
        for field, value in [('uid', '0'), ('gid', '0'), ('mode', '040755' if directory else '0100644')]:
            self.cmd(f'set_inode_field {q(path)} {field} {value}', True)
        out = self.tmp('context')
        out.write_bytes(label.encode() + b'\0')
        self.cmd('ea_set -f ' + q(out) + ' ' + q(path) + ' security.selinux', True)
        info = self.info(path)
        require(info and info['uid'] == info['gid'] == 0 and int(info['mode'], 8) == (0o755 if directory else 0o644),
                f'Ownership/mode read-back mismatch: {path}')
        require(self.label(path) == label, f'SELinux read-back mismatch: {path}')

    def mkdir(self, path, label):
        require(not self.exists(path), f'Unexpected existing path: {path}')
        self.cmd('mkdir ' + q(path), True)
        require(self.directory(path), f'mkdir failed: {path}')
        self.setmeta(path, label, True)


class Labels:
    """Use the real libselinux file-context matcher, not Python regex approximations."""
    def __init__(self, files, scratch):
        require(files, 'No SELinux file_contexts found in GSI')
        combined = Path(scratch) / 'combined_file_contexts'
        combined.write_bytes(b'\n'.join(p.read_bytes() for p in files) + b'\n')
        libname = ctypes.util.find_library('selinux')
        require(libname, 'Missing libselinux; install libselinux1')
        self.lib = C.CDLL(libname, use_errno=True)
        class Opt(C.Structure):
            _fields_ = [('type', C.c_int), ('value', C.c_char_p)]
        self.lib.selabel_open.argtypes = [C.c_uint, C.POINTER(Opt), C.c_uint]
        self.lib.selabel_open.restype = C.c_void_p
        self.lib.selabel_lookup_raw.argtypes = [C.c_void_p, C.POINTER(C.c_char_p), C.c_char_p, C.c_int]
        self.lib.selabel_close.argtypes = [C.c_void_p]
        self.lib.freecon.argtypes = [C.c_void_p]
        # SELABEL_CTX_FILE=0, SELABEL_OPT_PATH=3 (libselinux label.h).
        options = (Opt * 1)(Opt(3, os.fsencode(combined)))
        self.handle = self.lib.selabel_open(0, options, 1)
        require(self.handle, 'libselinux could not load combined file_contexts')

    def get(self, runtime_path, directory=False):
        context = C.c_char_p()
        rc = self.lib.selabel_lookup_raw(self.handle, C.byref(context), runtime_path.encode(),
                                         stat.S_IFDIR if directory else stat.S_IFREG)
        require(rc == 0, f'No SELinux file context match: {runtime_path}')
        result = context.value.decode()
        self.lib.freecon(C.cast(context, C.c_void_p))
        require(result.startswith('u:object_r:') and result.endswith(':s0'), f'Unexpected file context: {result}')
        return result

    def close(self):
        self.lib.selabel_close(self.handle)


def layout(fs):
    roots = [r for r in ['', '/system'] if fs.exists(r + '/framework/framework-res.apk')]
    require(len(roots) == 1, 'Cannot uniquely identify system image layout')
    return roots[0]


def preserve_snapshot(fs, overlay_dir, extra):
    result = {}
    paths = [p for p, _ in fs.tree(overlay_dir)] + extra
    for p in paths:
        if not fs.exists(p):
            continue
        i = fs.info(p)
        require(i['type'] in ('regular', 'directory'), f'Unsupported inode: {p}')
        result[p] = {'info': i, 'xattrs': fs.cmd('ea_list ' + q(p))}
        if i['type'] == 'regular':
            result[p]['sha256'] = sha(fs.extract(p))
    return result


def config_insert(data):
    root = ET.fromstring(data)
    require(root.tag == 'config', 'Overlay config root must be <config>')
    require(not root.findall('merge'), 'Overlay config uses <merge>; manual review required to preserve ordering')
    seen_mutable = False
    packages = set()
    for n in root:
        require(n.tag == 'overlay' and n.get('package'), 'Unsupported overlay config entry')
        require(n.get('package') not in packages, 'Duplicate package in overlay config')
        packages.add(n.get('package'))
        for attr in ['mutable', 'enabled']:
            require(n.get(attr, 'true' if attr == 'mutable' else 'false') in ('true', 'false'),
                    f'Invalid {attr} value in overlay config')
        require(n.get('package') != PACKAGE, 'Patch overlay already configured')
        mutable = n.get('mutable', 'true') == 'true'
        require(mutable or not seen_mutable, 'Invalid config: immutable overlay follows a mutable overlay')
        seen_mutable |= mutable
    offset = None
    parser = expat.ParserCreate()
    depth = 0
    def start(name, attrs):
        nonlocal depth, offset
        if depth == 1 and name == 'overlay' and attrs.get('mutable', 'true') == 'true' and offset is None:
            offset = parser.CurrentByteIndex
        depth += 1
    def end(name):
        nonlocal depth, offset
        depth -= 1
        if depth == 0 and offset is None:
            offset = parser.CurrentByteIndex
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.Parse(data, True)
    # Expat end index for a self-closing <config/> is after the tag: expand explicitly.
    if not list(root) and re.search(rb'<config\s*/>', data):
        return re.sub(rb'<config\s*/>', ('<config>\n' + config_entry() + '</config>').encode(), data, count=1)
    require(offset is not None, 'Could not locate config insertion point')
    output = data[:offset] + (config_entry() + '\n    ').encode() + data[offset:]
    parsed = ET.fromstring(output)
    require(len(parsed) == len(root) + 1, 'Config edit changed unexpected entries')
    return output


def config_entry():
    return f'    <overlay package="{PACKAGE}" enabled="true" mutable="false" />'


def priority_check(fs, root, partition, config, patched=False):
    order = ['system', 'vendor', 'odm', 'oem', 'product', 'system_ext']
    custom = root + '/product/overlay/partition_order.xml'
    for part in ['product', 'system_ext']:
        p = root + '/' + part
        require(not fs.exists(p) or fs.directory(p), f'Cannot inspect external/symlink partition for priority: {p}')
    require(partition != 'product' or fs.directory(root + '/system_ext'),
            'Product placement requires an in-image system_ext directory to inspect higher-priority overlays')
    require(not fs.exists(custom), 'Custom partition_order.xml found; manual priority review required')
    require(order.index(partition) > order.index('vendor'), 'Overlay must be after vendor in default partition order')
    entries = {n.get('package'): n.attrib for n in ET.fromstring(config)} if config else {}
    inventory = []
    own = 0
    for part in ['product', 'system_ext']:
        for path, mode in fs.tree(root + '/' + part + '/overlay'):
            if not stat.S_ISREG(mode) or not path.lower().endswith('.apk'):
                continue
            apk = fs.extract(path)
            attrs, _ = manifest_attrs(apk)
            resources = aapt('dump', 'resources', apk)
            mapping = ''
            if attrs.get('resourcesMap'):
                # A resource mapping can rename a resource; inspect its compiled XML too.
                for xmlpath in re.findall(r'\(file\) (res/\S+\.xml)', resources):
                    mapping += aapt('dump', 'xmltree', apk, '--file', xmlpath)
            conflicts = attrs.get('targetPackage') == 'android' and (RESOURCE in resources or RESOURCE in mapping)
            row = {'path': path, 'package': attrs.get('package'), 'priority': attrs.get('priority'),
                   'isStatic': attrs.get('isStatic'), 'same_resource': conflicts}
            inventory.append(row)
            if attrs.get('package') == PACKAGE:
                own += 1
                require(patched, f'Patch package already exists elsewhere: {path}')
                continue
            if not conflicts:
                continue
            require(order.index(part) <= order.index(partition), f'Higher partition has competing biometric overlay: {path}')
            if part == partition:
                if config:
                    cfg = entries.get(attrs.get('package'))
                    require(not cfg or cfg.get('mutable', 'true') == 'false' or cfg.get('enabled', 'false') == 'false',
                            f'Enabled mutable config can supersede patch: {path}')
                else:
                    require(attrs.get('isStatic') == 'true' and int(attrs.get('priority', '0')) < 999,
                            f'Competing dynamic/tied priority overlay requires manual review: {path}')
    require(not patched or own == 1, 'Expected exactly one installed patch package')
    return inventory


def patch(a):
    tools()
    source, output, apk = Path(a.input).resolve(), Path(a.output).absolute(), Path(a.apk).resolve()
    require(not output.exists() and not output.is_symlink(), 'Output already exists; refusing overwrite')
    require(source != output.resolve(), 'Input and output must differ')
    output.parent.mkdir(parents=True, exist_ok=True)
    report = Path(a.report or str(output) + '.report').absolute()
    require(not report.exists(), 'Report path already exists; choose a new output/report')
    report.mkdir(parents=True)
    before_hash = sha(source)
    info = image_info(source)
    require(info['free_bytes'] >= apk.stat().st_size * 4 + 4 * 1024 * 1024, 'Insufficient free EXT4 blocks; no automatic image resize')
    fsck(source, report / 'input-e2fsck.txt')
    temp_path = None
    try:
        with tempfile.TemporaryDirectory(prefix='patch-', dir=report) as scratch:
            fs = FS(source, scratch)
            root = layout(fs)
            part = a.partition
            partdir = root + '/' + part
            require(fs.directory(partdir), f'{partdir} must be a real directory inside the GSI; symlinks/external partitions unsupported')
            # Refuse symlink ancestors, including /system in a nested image.
            for path in filter(None, [root, partdir]):
                require(fs.directory(path), f'Unsupported path: {path}')
            overlaydir = partdir + '/overlay'
            require(not fs.exists(overlaydir) or fs.directory(overlaydir), 'Overlay directory is a symlink/non-directory')
            destdir = overlaydir + '/SmA1560FingerprintFix'
            dest = destdir + '/' + APK_NAME
            require(not fs.exists(destdir), 'Overlay already present; refusing double patch')
            cfgdir, cfgpath = overlaydir + '/config', overlaydir + '/config/config.xml'
            require(not fs.exists(cfgdir) or fs.directory(cfgdir), 'Overlay config directory is a symlink')
            config = fs.extract(cfgpath).read_bytes() if fs.exists(cfgpath) else None
            new_config = config_insert(config) if config is not None else None
            inventory = priority_check(fs, root, part, config)
            framework = fs.extract(root + '/framework/framework-res.apk')
            apk_result = verify_apk(apk, report / 'apk', framework, 'product' if part == 'product' else 'system',
                                    a.idmap2, not a.allow_unverified_idmap)
            context_paths = [root + '/etc/selinux/plat_file_contexts',
                             root + '/product/etc/selinux/product_file_contexts',
                             root + '/system_ext/etc/selinux/system_ext_file_contexts']
            contexts = [fs.extract(p) for p in context_paths if fs.exists(p)]
            labels = Labels(contexts, scratch)
            planned = {}
            for p, directory in [(overlaydir, True), (destdir, True), (dest, False)]:
                canonical = p[len(root):] if root else p
                planned[p] = {'label': labels.get(canonical, directory), 'directory': directory}
                if fs.exists(p):
                    i = fs.info(p)
                    require(i['uid'] == i['gid'] == 0 and int(i['mode'], 8) == (0o755 if directory else 0o644)
                            and fs.label(p) == planned[p]['label'], f'Unusual existing ownership/mode/label: {p}')
            if new_config is not None:
                planned[cfgpath] = {'label': fs.label(cfgpath), 'directory': False}
                require(planned[cfgpath]['label'] == labels.get(cfgpath[len(root):] if root else cfgpath),
                        'Existing config SELinux label differs from file_contexts; review before replacing')
                old_cfg = fs.info(cfgpath)
                require(old_cfg['uid'] == old_cfg['gid'] == 0 and int(old_cfg['mode'], 8) == 0o644,
                        'Unusual config ownership/mode; refusing replacement')
                xattrs = fs.cmd('ea_list ' + q(cfgpath))
                require(re.findall(r'^\s+([\w.]+) \(', xattrs, re.M) == ['security.selinux'],
                        'Config has extra/missing xattrs; refusing to discard them')
            labels.close()
            snapshot = preserve_snapshot(fs, overlaydir, [root + '/framework/framework-res.apk'] +
                                         [p for p in context_paths if fs.exists(p)])
            (report / 'priority-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
            (report / 'preserved-before.json').write_text(json.dumps(snapshot, indent=2) + '\n')
            fd, name = tempfile.mkstemp(prefix='.' + output.name + '.', suffix='.partial', dir=output.parent)
            os.close(fd)
            temp_path = Path(name)
            run(['cp', '--reflink=auto', '--sparse=always', '--', source, temp_path])
            os.chmod(temp_path, 0o600)
            target = FS(temp_path, scratch)
            for p in [overlaydir, destdir]:
                if not target.exists(p):
                    target.mkdir(p, planned[p]['label'])
            target.put(apk, dest)
            target.setmeta(dest, planned[dest]['label'])
            if new_config is not None:
                (report / 'overlay-config.original.xml').write_bytes(config)
                changed = Path(scratch) / 'overlay-config.patched.xml'
                changed.write_bytes(new_config)
                target.cmd('rm ' + q(cfgpath), True)
                require(not target.exists(cfgpath), 'Failed to remove copied config before replacement')
                target.put(changed, cfgpath)
                target.setmeta(cfgpath, planned[cfgpath]['label'])
                (report / 'overlay-config.patched.xml').write_bytes(new_config)
            after = preserve_snapshot(target, overlaydir, [root + '/framework/framework-res.apk'] +
                                      [p for p in context_paths if fs.exists(p)])
            for p, expected in snapshot.items():
                if p == cfgpath and new_config is not None:
                    continue
                require(after.get(p) == expected, f'Existing overlay/framework/context content or metadata changed: {p}')
            fsck(temp_path, report / 'output-e2fsck.txt')
            require(image_info(temp_path)['bytes'] == info['bytes'], 'Output image size changed')
            require(sha(source) == before_hash, 'Original input hash changed during patching')
            receipt = {'schema': 1, 'project': 'sm-a1560-fingerprint-fix', 'input_sha256': before_hash,
                       'output_sha256': sha(temp_path), 'apk_sha256': sha(apk), 'bytes': info['bytes'],
                       'partition': part, 'system_root_in_image': root, 'apk_path_in_image': dest,
                       'metadata': planned, 'config_path': cfgpath if new_config is not None else None,
                       'config_sha256': sha(report / 'overlay-config.patched.xml') if new_config is not None else None,
                       'idmap2': apk_result['idmap2'], 'preserved_paths_checked': len(snapshot),
                       'priority': 'offline default partition/config order checked; device must confirm effective value',
                       'device_enrollment': 'UNTESTED'}
            (report / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            with temp_path.open('rb') as f:
                os.fsync(f.fileno())
            # Atomic no-overwrite publish, even if another process creates the destination.
            os.link(temp_path, output)
            temp_path.unlink()
            temp_path = None
            (report / 'SHA256SUMS').write_text(f'{before_hash}  input.img\n{receipt["output_sha256"]}  {output.name}\n'
                                               f'{receipt["apk_sha256"]}  {APK_NAME}\n')
        print(json.dumps(receipt, indent=2))
        print('Image patched and checked OFFLINE. Fingerprint enrollment is UNTESTED.')
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def verify_image(a):
    tools()
    image = Path(a.image).resolve()
    receipt_path = Path(a.receipt or str(image) + '.report/receipt.json')
    receipt = json.loads(receipt_path.read_text())
    image_info(image)
    require(sha(image) == receipt['output_sha256'], 'Output image SHA-256 does not match receipt')
    if a.original:
        require(sha(a.original) == receipt['input_sha256'], 'Original input SHA-256 does not match receipt')
    report = Path(a.report or str(image) + '.recheck').absolute()
    report.mkdir(parents=True, exist_ok=True)
    fsck(image, report / 'e2fsck.txt')
    with tempfile.TemporaryDirectory(dir=report) as scratch:
        fs = FS(image, scratch)
        for path, meta in receipt['metadata'].items():
            i = fs.info(path)
            require(i and i['uid'] == i['gid'] == 0 and int(i['mode'], 8) == (0o755 if meta['directory'] else 0o644),
                    f'Unexpected ownership/mode: {path}')
            require(fs.label(path) == meta['label'], f'Unexpected SELinux label: {path}')
        apk = fs.extract(receipt['apk_path_in_image'])
        require(sha(apk) == receipt['apk_sha256'], 'Embedded APK SHA-256 mismatch')
        cfgpath = receipt['config_path']
        if cfgpath:
            require(sha(fs.extract(cfgpath)) == receipt['config_sha256'], 'Overlay config SHA-256 mismatch')
        framework = fs.extract(receipt['system_root_in_image'] + '/framework/framework-res.apk')
        result = verify_apk(apk, report / 'apk', framework, 'product' if receipt['partition'] == 'product' else 'system',
                            a.idmap2, a.require_idmap)
        config = fs.extract(cfgpath).read_bytes() if cfgpath else None
        inventory = priority_check(fs, receipt['system_root_in_image'], receipt['partition'], config, patched=True)
        if config:
            entries = [n for n in ET.fromstring(config) if n.get('package') == PACKAGE]
            require(len(entries) == 1 and entries[0].get('enabled') == 'true' and entries[0].get('mutable') == 'false',
                    'Patch overlay must be enabled and immutable in config')
        (report / 'priority-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
        result['image_sha256'] = receipt['output_sha256']
        result['original_sha256_verified'] = bool(a.original)
        result['metadata_readback'] = 'PASS'
        result['ext4_check'] = 'PASS'
        (report / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    patcher = sub.add_parser('patch')
    patcher.add_argument('--input', required=True)
    patcher.add_argument('--output', required=True)
    patcher.add_argument('--apk', default=str(Path(__file__).resolve().parents[1] / 'dist' / APK_NAME))
    patcher.add_argument('--partition', choices=['system_ext', 'product'], default='system_ext')
    patcher.add_argument('--report')
    patcher.add_argument('--idmap2')
    patcher.add_argument('--allow-unverified-idmap', action='store_true',
                         help='EXPERIMENT ONLY: logical resource/policy inspection if native host idmap2 is absent')
    v = sub.add_parser('verify')
    v.add_argument('image')
    v.add_argument('--original')
    v.add_argument('--receipt')
    v.add_argument('--report')
    v.add_argument('--idmap2')
    v.add_argument('--require-idmap', action='store_true')
    a = p.parse_args()
    patch(a) if a.command == 'patch' else verify_image(a)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, ET.ParseError, expat.ExpatError) as e:
        sys.exit(f'ERROR: {e}')
