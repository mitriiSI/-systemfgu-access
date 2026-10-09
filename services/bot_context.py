"""Per-update messenger context; never equate platform user IDs."""
from contextlib import contextmanager
from contextvars import ContextVar

current = ContextVar('midiary_bot_platform', default=None)

@contextmanager
def messenger(value):
    token = current.set(value)
    try:
        yield
    finally:
        current.reset(token)
