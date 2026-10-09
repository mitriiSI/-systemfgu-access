"""Teacher lists and group subject overrides kept apart from upstream schedules."""
import json
import re

from database import get_db

MAX_TEACHERS = 10


def subject_key(title):
    return ' '.join(title.casefold().replace('ё', 'е').split())


def teacher_list(value, *, strict=False):
    if strict:
        if not isinstance(value, list) or len(value) > MAX_TEACHERS:
            raise ValueError('Укажите не больше 10 преподавателей.')
    elif isinstance(value, str):
        value = re.split(r'[;,\n|]+', value)
    elif not isinstance(value, list):
        value = []
    result = []
    seen = set()
    for name in value:
        if not isinstance(name, str) or len(name) > 200:
            if strict:
                raise ValueError('Имя преподавателя должно быть не длиннее 200 символов.')
            continue
        name = ' '.join(name.split())
        key = subject_key(name)
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return result


def record_teachers(record):
    if isinstance(record.get('teachers'), list):
        return teacher_list(record['teachers'])
    return teacher_list(record.get('teachersNameFull') or record.get('teachersName') or record.get('teacher') or '')


def subject_overrides():
    connection = get_db()
    try:
        rows = connection.execute("SELECT item,body FROM content WHERE kind='subject_teachers'").fetchall()
    finally:
        connection.close()
    result = {}
    for row in rows:
        try:
            value = json.loads(row['body'])
            if isinstance(value, list):
                result[row['item']] = teacher_list(value, strict=True)
        except (ValueError, TypeError):
            continue
    return result


def with_teachers(record, overrides):
    title = record.get('disciplineFullName') or record.get('title') or ''
    names = overrides.get(subject_key(title), record_teachers(record))
    return dict(record, teachers=names, teacher='; '.join(names))
