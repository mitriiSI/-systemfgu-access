"""Bound disk use before accepting an authenticated material upload."""
import functools
import re
import shutil
import threading
from flask import request, jsonify
from config import DATA_DIR
from database import central_db

_write_lock = threading.Lock()
MAX_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 2000
RESERVE_BYTES = 256 * 1024 * 1024


def bounded_upload(view):
    @functools.wraps(view)
    def guarded(*args, **kwargs):
        from routes.auth import get_personal_owner
        owner = get_personal_owner()
        if request.form.get('scope')=='lesson':
            from services.material_access import require_item
            require_item(request.form.get('item',''),owner,lesson=True)
        size = request.content_length or 100 * 1024 * 1024
        with _write_lock:
            with central_db() as c:
                ids = [r[0] for r in c.execute('SELECT id FROM privacy_file_owners WHERE owner=?', (owner,))]
            count = used = 0
            for ident in ids:
                if not re.fullmatch('[a-f0-9]{48}', ident):
                    continue
                file = DATA_DIR / 'files' / ident
                if file.is_file() and not file.is_symlink():
                    count += 1
                    used += file.stat().st_size
            if count >= MAX_FILES or used + size > MAX_BYTES:
                return jsonify(error='Лимит ваших вложений — 2 ГБ и 2000 файлов.'), 400
            if shutil.disk_usage(DATA_DIR).free < size + RESERVE_BYTES:
                return jsonify(error='На сервере недостаточно свободного места для загрузки.'), 503
            return view(*args, **kwargs)
    return guarded
