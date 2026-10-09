"""Standalone upload reader. It never imports config, Flask or the database."""
import base64
import ctypes
import errno
import json
import os
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.table_schedules import preview_table
from services.spreadsheet_schedules import preview


def restrict(identity=65534):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(identity)
        os.setuid(identity)
    # Fail closed if Linux cannot install the network/privilege syscall filter.
    library = ctypes.CDLL('libseccomp.so.2')
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7fff0000)  # allow ordinary parsing syscalls
    if not context:
        raise RuntimeError('Sandbox unavailable')
    try:
        for name in ('socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4', 'ptrace',
                     'process_vm_readv', 'process_vm_writev', 'mount', 'umount2', 'unshare', 'setns', 'bpf',
                     'keyctl', 'add_key', 'request_key', 'perf_event_open'):
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and library.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError('Sandbox unavailable')
        if library.seccomp_load(context) != 0:
            raise RuntimeError('Sandbox unavailable')
    finally:
        library.seccomp_release(context)


def preload():
    # Import trusted libraries before dropping permissions; no upload is read.
    import pymupdf
    import openpyxl
    import xlrd
    import cv2
    import pytesseract
    from PIL import Image, ImageOps
    Image.init()
    cv2.setNumThreads(1)


def main():
    folder = Path(sys.argv[1])
    preload()
    restrict(int(sys.argv[2]))
    try:
        value = json.loads((folder / 'input.json').read_bytes())
        data = base64.b64decode(value['data'], validate=True)
        if value['filename'].lower().endswith(('.xlsx', '.xls')):
            result = preview(data, value['filename'], value['options'])
        else:
            result = preview_table(data, value['filename'], value['options'], value['group'])
        output = {'preview': result}
    except Exception:
        # No parser trace or native-library internals are exposed to callers.
        output = {'error': 'Не удалось прочитать документ. Проверьте формат, размер и таблицу расписания.'}
    (folder / 'output.json').write_text(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
