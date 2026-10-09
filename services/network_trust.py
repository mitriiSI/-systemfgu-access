"""Combine the runtime HTTPS trust store with a service's extra roots."""
import atexit
import os
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def _combined(base, extra, base_version, extra_version):
    with tempfile.NamedTemporaryFile(prefix='midiary-ca-', suffix='.pem', delete=False) as file:
        file.write(Path(base).read_bytes() + b'\n' + Path(extra).read_bytes())
        path = file.name
    atexit.register(lambda: Path(path).unlink(missing_ok=True))
    return path


def certificate_bundle(extra):
    """Keep TLS verification, including MAX's Russian CA and the runtime proxy."""
    base = os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('CURL_CA_BUNDLE')
    if not base or not extra or Path(base).resolve() == Path(extra).resolve():
        return extra or base or True
    return _combined(base, extra, Path(base).stat().st_mtime_ns, Path(extra).stat().st_mtime_ns)
