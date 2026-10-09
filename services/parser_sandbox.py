"""Parse uploads in bounded, credential-free child processes."""
import base64
import json
import os
import signal
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_slots = threading.BoundedSemaphore(1)
_identity_lock=threading.Lock()
_identities=set()
MAX_OUTPUT = 8 * 1024 * 1024
TIMEOUT = 120
WORKER = Path(__file__).with_name('parser_worker.py')


def parse_timetable(data, filename, options, group):
    if not _slots.acquire(blocking=False):
        raise ValueError('Распознавание занято. Повторите загрузку через минуту.')
    with _identity_lock:
        identity=20000+secrets.randbelow(45000)
        while identity in _identities:identity=20000+secrets.randbelow(45000)
        _identities.add(identity)
    try:
        with tempfile.TemporaryDirectory(prefix='midiary-parser-') as directory:
            folder = Path(directory)
            payload = {'data': base64.b64encode(data).decode(), 'filename': filename, 'options': options, 'group': group}
            source = folder / 'input.json'
            source.write_text(json.dumps(payload, ensure_ascii=False))
            source.chmod(0o600)
            # The worker drops to this unprivileged identity before reading input.
            if os.geteuid() == 0:
                os.chown(source, identity, identity)
                os.chown(folder, identity, identity)
            environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': directory,
                           'TMPDIR': directory, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHON_DOTENV_DISABLED': '1',
                           'OPENBLAS_NUM_THREADS': '1', 'OMP_THREAD_LIMIT': '1', 'OMP_NUM_THREADS': '1'}
            process = subprocess.Popen([sys.executable, '-I', str(WORKER), directory,str(identity)],
                                       env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            try:
                process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ValueError('Документ слишком сложный для распознавания. Разделите его на несколько файлов.') from None
            output = folder / 'output.json'
            try:
                descriptor = os.open(output, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OUTPUT:
                        raise ValueError()
                    result = json.loads(stream.read(MAX_OUTPUT + 1))
                if not isinstance(result, dict):
                    raise ValueError()
            except (OSError, ValueError):
                raise ValueError('Не удалось безопасно прочитать документ. Сохраните его заново или разделите на несколько файлов.') from None
            if result.get('error'):
                raise ValueError(result['error'])
            if process.returncode != 0 or not isinstance(result.get('preview'), dict):
                raise ValueError('Не удалось прочитать документ.')
            return result['preview']
    finally:
        with _identity_lock:_identities.discard(identity)
        _slots.release()
