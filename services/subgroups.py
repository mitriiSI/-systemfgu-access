"""Personal branches of a published timetable, independent of teacher edits.

Explicit subgroup labels work across different time slots. Unlabelled branches
are inferred only when the source puts different teachers in the same slot;
two teachers attached to a single period remain one class.
"""
import hashlib
import json
import re
from collections import defaultdict
from database import central_db, central_setting, current_group
from services.teachers import record_teachers, subject_key


def text(value):
    return ' '.join(str(value or '').split())


def normal(value):
    return text(value).casefold().replace('ё', 'е')


def preference_key(owner):
    return 'midiary_subgroups:' + owner + ':' + current_group()


def preferences(owner):
    try:
        value = json.loads(central_setting(preference_key(owner), '{}'))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def lecture(period):
    return normal(period.get('typeStr')).startswith(('лекц', 'lec'))


def teacher_signature(period):
    names = record_teachers(period)
    # Published teacher IDs keep a choice stable after name corrections.
    identity = text(period.get('teacherId'))
    return ('id:' + identity if identity and identity != '0' else
            'names:' + '|'.join(sorted(normal(name) for name in names))) if names else ''


def option_id(kind, value):
    return kind + ':' + hashlib.sha256(value.encode()).hexdigest()[:24]


def lesson_items(item):
    """Keep files and deadlines written before unlabelled branches had keys."""
    parts=item.split('|')
    if len(parts)==5 and re.fullmatch(r'teacher:[a-f0-9]{24}',parts[-1]):
        return [item,'|'.join(parts[:-1]+[''])]
    return [item]


def describe(days):
    subjects = {}
    for day in days:
        for lesson in day.get('lessons', []):
            for period in lesson.get('periods', []):
                title = text(period.get('disciplineFullName'))
                if not title:
                    continue
                subject = subject_key(title)
                info = subjects.setdefault(subject, {'subject': subject, 'title': title, 'records': []})
                info['records'].append((day, lesson, period))
    result = {}
    for subject, info in subjects.items():
        records = [(d, l, p) for d, l, p in info['records'] if not lecture(p)]
        labels = {normal(p.get('groups')) for _, _, p in records if text(p.get('groups'))}
        slots = defaultdict(set)
        for day, lesson, period in records:
            signature = teacher_signature(period)
            if signature:
                slots[day['date'], str(lesson.get('number', period.get('timeStart', '')))].add(signature)
        alternatives = set().union(*(values for values in slots.values() if len(values) > 1)) if slots else set()
        mode = 'group' if len(labels) > 1 else ('teacher' if len(alternatives) > 1 else '')
        if not mode:
            continue
        options = {}
        teachers_to_options = defaultdict(set)
        for _, _, period in records:
            value = normal(period.get('groups')) if mode == 'group' else teacher_signature(period)
            if not value or (mode == 'teacher' and value not in alternatives):
                continue
            ident = option_id(mode, value)
            entry = options.setdefault(ident, {'id': ident, 'group': text(period.get('groups')) if mode == 'group' else '', 'teachers': []})
            for name in record_teachers(period):
                if name not in entry['teachers']:
                    entry['teachers'].append(name)
            signature = teacher_signature(period)
            if signature:
                teachers_to_options[signature].add(ident)
        for entry in options.values():
            entry['label'] = ' · '.join(filter(None, [entry['group'], ', '.join(entry['teachers'])])) or 'Подгруппа'
        if len(options) > 1:
            result[subject] = dict(subject=subject, title=info['title'], mode=mode,
                                   options=options, teachers_to_options=teachers_to_options)
    return result


def branch(period, info):
    if lecture(period):
        return ''
    if info['mode'] == 'group':
        marker = normal(period.get('groups'))
        if marker:
            candidate = option_id('group', marker)
            return candidate if candidate in info['options'] else ''
        # A common unlabelled period must stay visible for every subgroup.
        return ''
    signature = teacher_signature(period)
    if not signature:
        return ''
    candidate = option_id('teacher', signature)
    return candidate if candidate in info['options'] else ''


def annotate(days, info=None):
    info = describe(days) if info is None else info
    for day in days:
        for lesson in day.get('lessons', []):
            for period in lesson.get('periods', []):
                period.pop('_diary_branch', None)
                period.pop('_diary_subgroup_label', None)
                subject = info.get(subject_key(text(period.get('disciplineFullName'))))
                if subject:
                    ident = branch(period, subject)
                    if ident:
                        period['_diary_branch'] = ident
                        period['_diary_subgroup_label'] = subject['options'][ident]['label']
    return days


def legacy_english(owner):
    if owner.startswith('admin:'):
        return central_setting('english_' + owner.split(':', 1)[1])
    if owner.startswith('member:'):
        with central_db() as c:
            row = c.execute('SELECT english FROM members WHERE code=?', (owner.split(':', 1)[1],)).fetchone()
        return row[0] if row else ''
    return ''


def selected_choices(owner, info):
    stored = preferences(owner)
    legacy = legacy_english(owner)
    chosen = {}
    for subject, entry in info.items():
        value = stored.get(subject, '')
        # An explicitly cleared choice means show all, including for old accounts.
        if subject not in stored and legacy and subject == subject_key('Английский язык'):
            value = next((option['id'] for option in entry['options'].values()
                          if normal(option['group']) == normal(legacy)), '')
        chosen[subject] = value if value in entry['options'] else ''
    return chosen


def catalog_for(owner, days):
    info = describe(days)
    chosen = selected_choices(owner, info)
    return [dict(subject=entry['subject'], title=entry['title'], selected=chosen[subject],
                 options=sorted(entry['options'].values(), key=lambda option: normal(option['label'])))
            for subject, entry in sorted(info.items())]


def save_choices(owner, days, choices):
    info = describe(days)
    if len(choices) > 100:
        raise ValueError('Слишком много предметов.')
    for subject, value in choices.items():
        if subject not in info or not isinstance(value, str) or (value and value not in info[subject]['options']):
            raise ValueError('Выберите подгруппу из расписания вашей учебной группы.')
    # Merge submitted subjects so source updates do not erase older choices.
    stored = preferences(owner)
    stored.update(choices)
    with central_db() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
                  (preference_key(owner), json.dumps(stored, ensure_ascii=False)))
    return catalog_for(owner, days)
