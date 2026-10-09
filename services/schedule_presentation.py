"""Separate timetable labels from metadata without changing saved lesson keys."""
import re

_MONTHS = r'января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря'
_DATES = re.compile(
    rf'(?<!\w)(?:[0-3]?\d\s+(?:{_MONTHS})(?:\s+20\d{{2}}(?:\s*г\.?)?)?'
    r'|[0-3]?\d[./][01]?\d(?:[./](?:20)?\d{2})?)(?!\w)', re.I)
_LOCATION = re.compile(
    r'\b(?:тр[её]хзальн\w*|(?:\d+[а-я-]*|перв\w*|втор\w*|трет\w*|'
    r'четв[её]рт\w*|главн\w*|нов\w*|стар\w*|спортивн\w*|учебн\w*)'
    r'(?:\s+учебн\w*)?)\s+корпус\b(?:\s*№\s*\d+)?', re.I)
_LINK = re.compile(r'(?:https?://|www\.)[^\s<>]+', re.I)


def subject_label(value):
    """The requested sentence case applies to every faculty, only in presentation."""
    text = ' '.join(str(value or '').split()).strip(' ,;')
    if re.fullmatch(r'(?:[А-Яа-яЁё]\s+){3,}[А-Яа-яЁё]', text):
        text = text.replace(' ', '')
    text = re.sub(r'\s*[-–]\s*', '-', text).lower()
    return re.sub(r'[a-zа-яё]', lambda match: match[0].upper(), text, count=1)


def geography_label(value, room='', source=None):
    """Dates and building names are not subject names; preserve the source key."""
    text = _LINK.sub(' ', str(value or ''))
    text = _DATES.sub(' ', text)
    if source is not None:
        # A two-digit day was previously mistaken for a classroom number.
        for stamp in _DATES.finditer(source):
            month=re.search(_MONTHS,stamp[0],re.I)
            if month:text=re.sub(r'\b'+re.escape(month[0])+r'\b',' ',text,flags=re.I)
    locations = []
    def location(match):
        locations.append(match[0].strip())
        return ' '
    text = _LOCATION.sub(location, text)
    # The original cell still has numeric dates before the old room extractor.
    # Exclude those numbers from newly parsed room labels as well.
    dates = list(_DATES.finditer(source or str(value or '')))
    date_numbers = {part for match in dates for part in re.findall(r'\d+', match[0])}
    rooms = [part.strip() for part in str(room or '').split(',') if part.strip()]
    if source is not None:
        actual_rooms = re.sub(_DATES, ' ', _LINK.sub(' ', source))
        rooms = [part for part in rooms if part not in date_numbers or
                 re.search(r'(?<!\d)'+re.escape(part)+r'(?!\d)', actual_rooms)]
    for place in locations:
        label = subject_label(place)
        if not any(label.casefold() == part.casefold() for part in rooms):
            rooms.append(label)
    return subject_label(' '.join(text.split()).strip(' ,;./-()')), ', '.join(rooms)[:120]
