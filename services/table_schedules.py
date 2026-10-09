"""Read faculty timetable grids, preserving merged cells and weekly variants.

PDF text is read with its cell coordinates. Photos use a local Russian/English
OCR engine; the grid is detected before words are assigned to cells. Uploaded
documents are temporary and are never executed or sent to an external service.
"""
import csv
import hashlib
import io
import re
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

MAX_FILE = 15 * 1024 * 1024
MAX_ROWS = 6000
MAX_PAGES = 20
_ocr_lock = threading.BoundedSemaphore(2)
DAYS = ('понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье')
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TIME = re.compile(r'(\d\s*\d?)\s*[.:\-]\s*(\d\s*\d)')
TEACHER = re.compile(
    r'(?:(?:ст\s*\.\s*)?(?:преп(?:одаватель)?|пр)|проф(?:ессор)?|доц(?:ент)?|'
    r'зав\s*\.\s*каф|с\s*\.\s*н\s*\.\s*с)\s*\.?\s*'
    r'\.?\s*([А-ЯЁA-Z][а-яёA-Za-z-]+\s+[А-ЯЁA-Z]\s*\.\s*[А-ЯЁA-Z]\s*\.)', re.I)
NAME = re.compile(r'([А-ЯЁA-Z][а-яёA-Za-z-]+\s+[А-ЯЁA-Z]\s*\.\s*[А-ЯЁA-Z]\s*\.)')
KIND = re.compile(r'(?<![а-яё])(?:\(\s*)?(Лк|Сем|Лб|Пз|лекция|семинар|лабораторная)(?:\s*\))?(?![а-яё])', re.I)
WEEK = re.compile(r'(нечетн\w*|нечётн\w*|четн\w*|чётн\w*|верхн\w*|нижн\w*|неч|чет|чёт)\s*(?:недел\w*|нед\.?|н\.?|(?=\)))', re.I)
GROUP = re.compile(r'^(?:[ККKк]-?\s*)?\d{3}[а-яёa-z_\s]*$|^\d{1,2}\s*(?:англ|нем|фр|франц|исп|кит|итал|гр\s*упп)[\s\S]{0,65}$', re.I)


def text(value):
    return ' '.join(str(value or '').replace('\xa0', ' ').split())


def group_name(value):
    value = text(value)
    value = re.sub(r'(\d)\s*(англ|нем|фр|франц|исп|кит|итал)', r'\1 \2', value, flags=re.I)
    value = re.sub(r'гр\s+упп', 'групп', value, flags=re.I)
    numbered = re.fullmatch(r'(\d{1,2})\s*групп[аы](?:\s*(?:РЯ|АЯ))?', value, re.I)
    reversed_number = re.fullmatch(r'групп[аы]\s*(\d{1,2})', value, re.I)
    if numbered or reversed_number:
        value = (numbered or reversed_number)[1] + ' группа'
    value = re.sub(r'([ККKк])\s*-\s*', 'К-', value)
    if re.match(r'^\d{3}', value):
        value = re.sub(r'\s+', '_', value).strip('_')
        value = re.sub('_+', '_', value)
    return value


def signature(value):
    return re.sub(r'[^\w]', '', group_name(value).casefold().replace('ё', 'е'))


def ocr_text(value):
    value = re.sub(r'(?i)(?:rp|rр|гp)\s*\.?\s*(?=\d)', 'гр.', value)
    value = re.sub(r'(?m)^\s*де(?=[А-ЯЁ])', 'дв', value)
    value = re.sub(r'(?<=,)[ \t]*(?:16|Л6)(?=[ \t]*,)', ' Лб', value)
    mapping = str.maketrans('ABCEHKMOPTXY30', 'АВСЕНКМОРТХУЗО')
    def initials(match):
        return match[1]+' '+match[2].upper().translate(mapping)+'.'+match[3].upper().translate(mapping)+'.'
    value = re.sub(r'([А-ЯЁ][а-яё-]+)\s+([А-Яа-яЁёA-Za-z30])\s*\.\s*([А-Яа-яЁёA-Za-z30])\s*\.', initials, value)
    return value


def weekday(value, partial=False):
    normal = re.sub(r'[^а-яё]', '', str(value).casefold())
    matches = [i for i, name in enumerate(DAYS) if normal == name or
               (partial and len(normal) >= 3 and (name.startswith(normal) or name.endswith(normal)))]
    return matches[0] if len(matches) == 1 else None


def interval(value):
    value = re.sub(r'\b[Зз]\s*пара', '3 пара', text(value))
    value = re.sub(r'\d{1,2}\s*пара', '', text(value), flags=re.I)
    if re.search(r'[А-Яа-яЁёA-Za-z]', value):
        return None
    matches = TIME.findall(value)
    if len(matches) < 2:
        return None
    values = []
    for hour, minute in matches[:2]:
        hour, minute = int(hour.replace(' ', '')), int(minute.replace(' ', ''))
        if hour > 23 or minute > 59:
            return None
        values.append(f'{hour:02}:{minute:02}')
    return tuple(values) if values[1] > values[0] else None


@dataclass
class Cell:
    x0: float
    y0: float
    x1: float
    y1: float
    value: str

    @property
    def x(self):
        return (self.x0 + self.x1) / 2

    @property
    def y(self):
        return (self.y0 + self.y1) / 2


@dataclass
class Grid:
    cells: list
    context: str = ''
    page: int = 1
    ocr: bool = False


def _zip(data):
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        if len(book.infolist()) > 2000 or sum(x.file_size for x in book.infolist()) > 40 * 1024 * 1024:
            book.close()
            raise ValueError('Слишком большой документ после распаковки.')
        return book
    except zipfile.BadZipFile:
        raise ValueError('Не удалось прочитать документ Word.')


def docx_grids(data):
    with _zip(data) as book:
        try:
            root = ET.fromstring(book.read('word/document.xml'))
        except (KeyError, ET.ParseError, DefusedXmlException):
            raise ValueError('Не удалось прочитать документ Word.')
    context = '\n'.join(''.join(p.itertext()) for p in root.iter(W + 'p'))
    grids = []
    for index, table in enumerate(root.iter(W + 'tbl')):
        if index >= 80:
            raise ValueError('В документе слишком много таблиц.')
        columns = [max(1, int(c.get(W + 'w', '1000'))) / 20 for c in table.findall(W + 'tblGrid/' + W + 'gridCol')]
        if not columns:
            continue
        edges = [0]
        for width in columns:
            edges.append(edges[-1] + width)
        cells, merged = [], {}
        for number, row in enumerate(table.findall(W + 'tr')):
            if number > 1000:
                raise ValueError('В таблице слишком много строк.')
            offset = row.find(W + 'trPr/' + W + 'gridBefore')
            col = int(offset.get(W + 'val', '0')) if offset is not None else 0
            for entry in row.findall(W + 'tc'):
                span = entry.find(W + 'tcPr/' + W + 'gridSpan')
                count = int(span.get(W + 'val', '1')) if span is not None else 1
                finish = min(col + count, len(columns))
                if col >= len(columns):
                    break
                value = '\n'.join(''.join(t.text or '' for t in p.iter(W + 't')) for p in entry.findall(W + 'p'))
                merge = entry.find(W + 'tcPr/' + W + 'vMerge')
                if merge is not None and merge.get(W + 'val') != 'restart' and col in merged:
                    merged[col].y1 = (number + 1) * 100
                else:
                    cell = Cell(edges[col], number * 100, edges[finish], (number + 1) * 100, value)
                    cells.append(cell)
                    if merge is not None:
                        for key in range(col, finish):
                            merged[key] = cell
                    else:
                        for key in range(col, finish):
                            merged.pop(key, None)
                col = finish
        grids.append(Grid(cells, context, index + 1))
    return grids


def doc_grids(data):
    with tempfile.TemporaryDirectory(prefix='diary-word-') as folder:
        path = Path(folder) / 'schedule.doc'
        path.write_bytes(data)
        try:
            output = subprocess.run(['antiword', '-x', 'db', str(path)], capture_output=True, timeout=25)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            raise ValueError('Не удалось прочитать DOC. Сохраните документ как PDF или DOCX.')
    if output.returncode or len(output.stdout) > 10 * 1024 * 1024:
        raise ValueError('Не удалось прочитать DOC. Сохраните документ как PDF или DOCX.')
    try:
        root = ET.fromstring(output.stdout)
    except (ET.ParseError, DefusedXmlException):
        raise ValueError('Не удалось прочитать таблицы DOC.')
    context = '\n'.join(''.join(p.itertext()) for p in root.iter('para'))
    grids = []
    for index, group in enumerate(root.iter('tgroup')):
        edges = [0]
        for column in group.findall('colspec'):
            edges.append(edges[-1] + float(re.sub(r'[^\d.]', '', column.get('colwidth', '100'))))
        cells = []
        for number, row in enumerate(group.findall('./tbody/row')):
            col = 0
            for entry in row.findall('entry'):
                if col + 1 >= len(edges):
                    break
                cells.append(Cell(edges[col], number * 100, edges[col + 1], (number + 1) * 100, ''.join(entry.itertext()).strip()))
                col += 1
        grids.append(Grid(cells, context, index + 1))
    return grids


def _photo_grid(data, page=1):
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as original:
            if original.width * original.height > 32_000_000:
                raise ValueError('Фото слишком большое. Уменьшите его до 32 мегапикселей.')
            picture = ImageOps.exif_transpose(original).convert('RGB')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('Не удалось прочитать фото. Загрузите JPG, PNG или WEBP.')
    picture.thumbnail((4200, 4200))
    frame = np.array(picture)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    # Straighten the photographed sheet when its four corners are visible.
    edges = cv2.Canny(gray, 60, 180)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        corners = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
        if len(corners) != 4 or cv2.contourArea(contour) < gray.size * .25:
            continue
        points = corners.reshape(4, 2).astype('float32')
        sums, differences = points.sum(axis=1), np.diff(points, axis=1).ravel()
        ordered = np.array([points[np.argmin(sums)], points[np.argmin(differences)], points[np.argmax(sums)], points[np.argmax(differences)]])
        width = int(max(np.linalg.norm(ordered[1] - ordered[0]), np.linalg.norm(ordered[2] - ordered[3])))
        height = int(max(np.linalg.norm(ordered[3] - ordered[0]), np.linalg.norm(ordered[2] - ordered[1])))
        transform = cv2.getPerspectiveTransform(ordered, np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]))
        frame = cv2.warpPerspective(frame, transform, (width, height))
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        break
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, gray.shape[1] // 45), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, min(20, gray.shape[0] // 200)))))
    lines = cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 15 or height < 12 or width * height > gray.size * .7:
            continue
        if cv2.contourArea(contour) < width * height * .72:
            continue
        boxes.append((x, y, x + width, y + height))
    # Remove outlines enclosing several cells; retain the inner cell rectangle.
    boxes = [box for box in boxes if not any(other != box and box[0] <= other[0] and box[1] <= other[1] and box[2] >= other[2] and box[3] >= other[3] for other in boxes)]
    clean = cv2.inpaint(frame, lines, 2, cv2.INPAINT_TELEA)
    try:
        result = pytesseract.image_to_data(clean, lang='rus+eng', config='--psm 11', output_type=pytesseract.Output.DICT, timeout=70)
    except (RuntimeError, pytesseract.TesseractNotFoundError):
        raise ValueError('Не удалось распознать фото. Попробуйте более чёткое фото или исходный PDF.')
    words = []
    for i, value in enumerate(result['text']):
        if not value.strip():
            continue
        words.append((result['left'][i], result['top'][i], result['width'][i], result['height'][i], value))
    cells = []
    for x0, y0, x1, y1 in boxes:
        found = [w for w in words if x0 <= w[0] + w[2] / 2 <= x1 and y0 <= w[1] + w[3] / 2 <= y1]
        found.sort(key=lambda w: (w[1], w[0]))
        rows, current_y = [], -1000
        for x, y, width, height, value in found:
            if abs(y - current_y) > max(7, height * .7):
                rows.append([])
                current_y = y
            rows[-1].append((x, value))
        value = '\n'.join(' '.join(value for x,value in sorted(row)) for row in rows)
        if y1 - y0 > (x1 - x0) * 2 and x0 < gray.shape[1] * .15:
            crop = Image.fromarray(frame[y0+3:y1-3, x0+3:x1-3])
            for angle in (270, 90):
                rotated = pytesseract.image_to_string(crop.rotate(angle, expand=True), lang='rus', config='--psm 7', timeout=15)
                if weekday(rotated) is not None:
                    value = rotated.strip()
                    break
        cells.append(Cell(x0, y0, x1, y1, ocr_text(value)))
    context = ' '.join(w[4] for w in sorted(words, key=lambda w: (w[1], w[0])))
    if not cells:
        raise ValueError('Границы таблицы не найдены. Сфотографируйте всю таблицу с днями, временем и заголовками групп.')
    return Grid(cells, context, page, True)


def read_grids(data, filename):
    if not data or len(data) > MAX_FILE:
        raise ValueError('Загрузите файл размером до 15 МБ.')
    extension = Path(filename).suffix.casefold()
    if extension == '.docx':
        return docx_grids(data)
    if extension == '.doc':
        return doc_grids(data)
    if extension in ('.png', '.jpg', '.jpeg', '.webp'):
        if not _ocr_lock.acquire(blocking=False):
            raise ValueError('Распознавание занято. Повторите загрузку через минуту.')
        try:
            return [_photo_grid(data)]
        finally:
            _ocr_lock.release()
    if extension != '.pdf':
        raise ValueError('Поддерживаются фото JPG, PNG, WEBP, документы PDF, DOCX, DOC и таблицы Excel.')
    import pymupdf
    try:
        book = pymupdf.open(stream=data, filetype='pdf')
    except Exception:
        raise ValueError('Не удалось открыть PDF.')
    with book:
        if book.needs_pass:
            raise ValueError('Снимите пароль с PDF перед загрузкой.')
        if not 1 <= len(book) <= MAX_PAGES:
            raise ValueError('PDF должен содержать от 1 до 20 страниц.')
        grids, context = [], ''
        for index, page in enumerate(book):
            content = page.get_text()
            if len(content.strip()) < 30:
                if not _ocr_lock.acquire(blocking=False):
                    raise ValueError('Распознавание занято. Повторите загрузку через минуту.')
                try:
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(min(3, 4200 / max(page.rect.width, page.rect.height)), min(3, 4200 / max(page.rect.width, page.rect.height))))
                    grids.append(_photo_grid(pix.tobytes('png'), index + 1))
                finally:
                    _ocr_lock.release()
                continue
            if re.search(r'учебных занятий\s+\d\s*курса', content, re.I):
                context = content
            else:
                context += '\n' + content
            for table in page.find_tables().tables:
                cells = []
                seen = set()
                extracted = table.extract()
                for r, row in enumerate(table.rows):
                    for col, box in enumerate(row.cells):
                        if box is None or box in seen:
                            continue
                        seen.add(box)
                        cells.append(Cell(*box, extracted[r][col] or ''))
                # A PDF page break can split the rotated day label and leave
                # its cell open. Recover it from text and the column border.
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        if abs(line['dir'][1]) < .5:
                            continue
                        label = ''.join(span['text'] for span in line['spans'])
                        day = weekday(label, partial=True)
                        if day is None:
                            continue
                        x0, y0, x1, y1 = line['bbox']
                        middle = (y0 + y1) / 2
                        if not table.bbox[1] - 3 <= middle <= table.bbox[3] + 3:
                            continue
                        if any(weekday(c.value) == day and c.y0 - 3 <= middle <= c.y1 + 3 for c in cells):
                            continue
                        borders = [d['rect'] for d in page.get_drawings() if d['rect'].width <= 1.5
                                   and abs(d['rect'].x0 - x1) < 3
                                   and d['rect'].y0 - 3 <= middle <= d['rect'].y1 + 3]
                        if borders and table.bbox[0] - 3 <= x0:
                            border = min(borders, key=lambda r: abs(r.x0 - x1))
                            cells.append(Cell(x0, max(table.bbox[1], border.y0), border.x1,
                                              min(table.bbox[3], border.y1), DAYS[day]))
                grids.append(Grid(cells, context, index + 1))
        return grids


def headers(grid):
    timed = [cell for cell in grid.cells if interval(cell.value)]
    top = min((cell.y0 for cell in timed), default=float('inf'))
    left = max((cell.x1 for cell in timed if cell.y0 <= top + 2), default=0)
    rows = {}
    for cell in grid.cells:
        name = group_name(cell.value)
        if not timed and re.fullmatch(r'\d{3}', name):
            continue
        if cell.y1 <= top + 2 and cell.x0 >= left - 2 and GROUP.fullmatch(name):
            rows.setdefault(round(cell.y0), []).append(cell)
    if rows:
        return sorted(max(rows.values(), key=lambda row: len(row)), key=lambda cell: cell.x0)
    if not timed:
        return []
    # Master's timetables identify programmes and languages instead of numbers.
    candidates = [cell for cell in grid.cells if cell.y1 <= top + 2 and cell.x0 >= left - 2
                  and 3 <= len(text(cell.value)) <= 200 and weekday(cell.value) is None
                  and not re.search(r'утвержда|декан|семестр|уч\.\s*г|время|20\s*\d\s*\d|\b(?:проф|доц|ст\.\s*пр|преп)\s*\.', cell.value, re.I)]
    if candidates:
        y = max(cell.y0 for cell in candidates)
        return sorted([cell for cell in candidates if abs(cell.y0 - y) < 2], key=lambda cell: cell.x0)
    return []


def catalogue(data, filename):
    return list(dict.fromkeys(group_name(cell.value) for grid in read_grids(data, filename) for cell in headers(grid)))


def _bounds(grids, options):
    context = '\n'.join(grid.context for grid in grids)
    dates = re.search(r'\(?\s*(\d{2}\.\d{2}\.20\d{2})\s*[-–—]\s*(\d{2}\.\d{2}\.20\d{2})\s*\)?', context)
    if dates:
        first, last = (date(*map(int, value.split('.')[::-1])) for value in dates.groups())
    else:
        year = re.search(r'(20\d{2})\s*[/–-]\s*20\d{2}', text(context))
        current = date.today()
        start_year = int(year[1]) if year else current.year
        spring = bool(re.search(r'весн|весенн', context, re.I)) or (not year and current.month < 8)
        first = date(start_year + (1 if year and spring else 0), 2 if spring else 9, 1)
        last = date(first.year, 6 if spring else 12, 30 if spring else 31)
    try:
        first = date.fromisoformat(options['from']) if options.get('from') else first
        last = date.fromisoformat(options['to']) if options.get('to') else last
        anchor = date.fromisoformat(options['week_anchor']) if options.get('week_anchor') else first
    except (TypeError, ValueError):
        raise ValueError('Укажите корректные даты периода и первой нечётной недели.')
    if not 0 <= (last - first).days <= 366:
        raise ValueError('Укажите период не длиннее года.')
    return first, last, anchor - timedelta(days=anchor.weekday())


def _parts(raw):
    # Lines of dashes separate alternate weeks. Language labs and electives
    # often share one merged cell, with one teacher per independent option.
    pieces = re.split(r'[-–—]{4,}|(?m:^\s*[-–—][-–— \t]*$)', raw)
    result = []
    for piece in pieces:
        languages = list(re.finditer(r'(?m)^\s*(?:\d[,\d]*\s*)?(?:нем|фр|франц|ит|итал|исп|кит)\s*\.(?:\s*яз\s*\.?)?', piece, re.I))
        if len(languages) > 1:
            prefix = piece[:languages[0].start()].strip()
            result.extend((prefix + '\n' if prefix else '') + piece[a.start():b.start() if b else len(piece)] for a,b in zip(languages,languages[1:]+[None]))
            continue
        starts = [m.start() for m in re.finditer(r'(?m)^\s*(?:(?:[Пп]рофессиональный\s+)?(?:[Аа]нглийский|[Рр]усский|[Кк]итайский|[Нн]емецкий|[Фф]ранцузский|[Ии]спанский|[Ии]тальянский)\s+язык|дв\s*[А-ЯЁA-Z])', piece)]
        if len(starts) > 1:
            result.extend(piece[a:b] for a, b in zip(starts, starts[1:] + [len(piece)]))
        else:
            result.append(piece)
    return [piece.strip() for piece in result if re.search('[А-Яа-яЁёA-Za-z]', piece)]


def _lesson(raw, times):
    value = text(raw)
    if not value or weekday(value) is not None:
        return None
    override = re.search(r'(?:^\s*\(?\s*|\(\s*)(\d{1,2}\s*[.:]\s*\d{2}\s*[-–—]\s*\d{1,2}\s*[.:]\s*\d{2})(?:\)|(?=\s|$))', value)
    if override and interval(override[1]):
        times = interval(override[1])
        value = value[:override.start()] + value[override.end():]
    weeks = WEEK.findall(value)
    week = ''
    if weeks:
        week = 'odd' if weeks[0].casefold().startswith(('не', 'верх')) else 'even'
    starts = re.search(r'(?<![а-я])с\s*(\d{1,2})\.(\d{2})(?:\.(20\d{2}))?', value, re.I)
    until = re.search(r'(?<![а-я])до\s*(\d{1,2})\.(\d{2})(?:\.(20\d{2}))?', value, re.I)
    teachers = [text(m[1]) for m in TEACHER.finditer(value)]
    if not teachers:
        teachers = [text(m[1]) for m in NAME.finditer(value)]
    teachers = [re.sub(r'([А-Яа-яЁёA-Za-z])\s*\.\s*([А-Яа-яЁёA-Za-z])\s*\.$',lambda m:m[1].upper()+'.'+m[2].upper()+'.', name) for name in teachers]
    marker = re.search(r'(?:гр\.?|групп[аы]?|п/г)\s*\.?\s*(\d{1,2})\b', value, re.I)
    subgroup = ('Группа ' + marker[1]) if marker else ''
    language = re.search(r'(?<![А-Яа-я])(?:\d[,\d]*\s*)?(нем|фр|франц|ит|итал|исп|кит)\s*\.(?:\s*яз\s*\.?)?', value, re.I)
    if language and re.search(r'(?:второй|вторые)\s+иностранн|вторые\s+языки', value, re.I):
        subgroup = {'нем':'Немецкий','фр':'Французский','франц':'Французский','ит':'Итальянский','итал':'Итальянский','исп':'Испанский','кит':'Китайский'}[language[1].casefold()]
    match = KIND.search(value)
    kind = {'лк': 'Лекция', 'сем': 'Семинар', 'лб': 'Лабораторная', 'пз': 'Практика', 'лекция': 'Лекция', 'семинар': 'Семинар', 'лабораторная': 'Лабораторная'}.get(match[1].casefold(), 'Пара') if match else 'Пара'
    room_match = re.search(r'ауд\s*\.?\s*([^,;()]*?)(?=\s+(?:ст\s*\.|пр(?:\.|еп)|проф|доц|зав)|[,;()]|$)', value, re.I)
    room = text(room_match[1]) if room_match else ''
    cut = match.start() if match else (min((m.start() for m in TEACHER.finditer(value)), default=len(value)))
    title = value[:cut]
    title = re.sub(r'^дв\s*(?=[А-ЯЁA-Z])', '', title)
    title = re.sub(r'(?:гр\.?|групп[аы]?|п/г)\s*\.?\s*\d{1,2}\s*[,;]?', '', title, flags=re.I)
    if language and subgroup and not marker:
        title = re.sub(re.escape(language[0]), '', title, count=1).strip()
    title = re.sub(r'ауд\s*\.[\s\S]*$', '', title, flags=re.I)
    title = WEEK.sub('', title)
    title = re.sub(r'\(\s*\)|с\s*\d{1,2}\.\d{2}(?:\.20\d{2})?(?:\s*года)?', '', title, flags=re.I)
    if not room:
        ending = re.search(r'\s+(\d{2,4}[А-Яа-яA-Za-z]?)\s*$', value)
        if ending:
            room = ending[1]
            title = re.sub(r'\s+' + re.escape(room) + r'\s*$', '', title)
    if not match:
        title = NAME.sub('', title)
    title = text(title).strip(' ,.;-/()')
    if re.fullmatch(r'(?:[А-ЯЁ]\s+){2,}[А-ЯЁ]', title):
        title = title.replace(' ', '').capitalize()
    if not re.search('[А-Яа-яЁёA-Za-z]', title) or len(title) < 2:
        return None
    return {'title': title[:300], 'start': times[0], 'end': times[1], 'teacher': ', '.join(dict.fromkeys(teachers))[:200],
            'room': room[:120], 'type': kind, 'group': subgroup, 'week': week,
            '_begins': starts.groups() if starts else None, '_until': until.groups() if until else None,
            '_last_month_weekday': bool(re.search(r'последн\w*\s+(?:' + '|'.join(DAYS) + r')\s+каждого\s+месяца', value, re.I)),
            '_exclude': re.findall(r'(\d{2}\.\d{2}\.20\d{2})\s+разово\s+отмена', value, re.I)}


def preview_table(data, filename, options, selected_group):
    grids = read_grids(data, filename)
    if not grids:
        raise ValueError('Таблицы не найдены. Загрузите фото таблицы или PDF с сеткой.')
    bell_times=options.get('bell_times') or []
    for grid in grids:
        time_headers=[cell for cell in grid.cells if text(cell.value).casefold() in ('время','пара','№ пары','номер пары')]
        day_cells=[cell for cell in grid.cells if weekday(cell.value) is not None]
        for cell in grid.cells:
            numbered=re.fullmatch(r'(\d{1,2})\s*(?:пара)?',text(cell.value),re.I)
            if not numbered or not 1<=int(numbered[1])<=len(bell_times):continue
            in_column=any(abs(cell.x0-header.x0)<2 and abs(cell.x1-header.x1)<2 and cell.y0>=header.y1 for header in time_headers)
            after_day=any(abs(cell.x0-day.x1)<2 and day.y0<=cell.y<=day.y1 for day in day_cells)
            if in_column or after_day:
                start,end=bell_times[int(numbered[1])-1]
                cell.value=numbered[1]+' пара\n'+start+'\n'+end
    selected = group_name(options.get('table_group') or selected_group)
    target = signature(selected)
    scope = [grid for grid in grids if any(signature(cell.value) == target for cell in headers(grid))]
    first, last, anchor = _bounds(scope or grids, options)
    templates, errors, warnings = [], [], []
    current_day = None
    previous_start = None
    selection_ratio = None
    detected_groups = set()
    matched = False
    active = True
    for grid in grids:
        if not grid.cells:
            continue
        found = headers(grid)
        detected_groups.update(group_name(cell.value) for cell in found)
        chosen = next((cell for cell in found if signature(cell.value) == target), None)
        if found and chosen is None and len(found) > 1:
            active = False
            continue
        if not found and not active:
            continue
        if chosen:
            active = True
            matched = True
            lo, hi = min(cell.x0 for cell in grid.cells), max(cell.x1 for cell in grid.cells)
            selection_ratio = (chosen.x - lo) / max(1, hi - lo)
        if found and chosen is None and len(found) == 1:
            # A single-group crop has no ambiguity; retain the user's label.
            selection_ratio = (found[0].x - min(cell.x0 for cell in grid.cells)) / max(1, max(cell.x1 for cell in grid.cells) - min(cell.x0 for cell in grid.cells))
        times = sorted([cell for cell in grid.cells if interval(cell.value)], key=lambda cell: (cell.y0, cell.x0))
        if not times:
            continue
        for time_cell in times:
            # A day label covers its own rows only. In a split PDF the next
            # day's label may be on the following page, while its first pair
            # is already at the bottom of this one.
            day_cells = [cell for cell in grid.cells if weekday(cell.value) is not None
                         and cell.y0 - 2 <= time_cell.y < cell.y1 + 2]
            times_value = interval(time_cell.value)
            if day_cells:
                current_day = weekday(max(day_cells, key=lambda cell: cell.y0).value)
            elif current_day is not None and previous_start and times_value[0] < previous_start:
                current_day = (current_day + 1) % 7
            previous_start = times_value[0]
            if current_day is None:
                errors.append({'row': grid.page, 'message': 'Не удалось определить день недели. Включите в фото столбец с днями.'})
                continue
            x = chosen.x if chosen else (min(cell.x0 for cell in grid.cells) + selection_ratio * (max(cell.x1 for cell in grid.cells) - min(cell.x0 for cell in grid.cells)) if selection_ratio is not None else None)
            candidates = [cell for cell in grid.cells if cell.x0 >= time_cell.x1 - 2 and cell.y0 - 2 <= time_cell.y <= cell.y1 + 2 and cell is not time_cell]
            if x is not None:
                candidates = [cell for cell in candidates if cell.x0 - 2 <= x <= cell.x1 + 2]
            elif len(candidates) > 1:
                errors.append({'row': grid.page, 'message': 'Укажите заголовок своей группы в таблице.'})
                continue
            number_match = re.search(r'(\d{1,2})\s*пара', re.sub(r'\b[Зз]\s*пара', '3 пара', time_cell.value), re.I)
            for cell in candidates:
                fragments = _parts(cell.value)
                alternatives = len(fragments) > 1 and all(re.match(r'^дв\s*[А-ЯЁA-Z]', text(piece)) for piece in fragments)
                language_choice = bool(re.search(r'Английский язык', cell.value, re.I)
                                       and re.search(r'Русский язык как иностранный', cell.value, re.I))
                for fragment in fragments:
                    lesson = _lesson(fragment, times_value)
                    if lesson is None:
                        continue
                    pair_starts=[pair[0] for pair in bell_times] if bell_times else ('09:00', '10:45', '13:00', '14:45', '16:30', '18:10', '19:50')
                    number = int(number_match[1]) if number_match else next((i + 1 for i, start in enumerate(pair_starts) if start == times_value[0]), 0)
                    lesson.update(weekday=current_day, number=number, page=grid.page)
                    if alternatives:
                        lesson['choice'] = 'elective:' + str(current_day) + ':' + str(number) + ':' + lesson['week']
                    elif language_choice:
                        lesson['choice'] = 'primary-language'
                    # A cell with an explicit interval must not become two
                    # copies of the same lesson when it spans several rows.
                    ident = hashlib.sha256(repr((current_day, lesson['title'], (lesson['start'], lesson['end']), lesson['teacher'], lesson['group'], lesson['week'], lesson['type'])).encode()).hexdigest()[:24]
                    lesson['template_id'] = ident
                    if not any(row['template_id'] == ident for row in templates):
                        templates.append(lesson)
    if detected_groups and not matched and len(detected_groups) > 1:
        errors.append({'row': 1, 'message': 'Группа «' + selected + '» не найдена. Выберите её точный заголовок из файла.'})
    rows = []
    for template in templates:
        begins, until = first, last
        for key, is_start in (('_begins', True), ('_until', False)):
            marker = template[key]
            if marker:
                try:
                    limit = date(int(marker[2] or first.year), int(marker[1]), int(marker[0]))
                    if is_start:
                        begins = max(begins, limit)
                    else:
                        until = min(until, limit)
                except ValueError:
                    warnings.append('Не удалось прочитать дату начала занятия: ' + template['title'])
        current = begins + timedelta(days=(template['weekday'] - begins.weekday()) % 7)
        while current <= until:
            parity = ((current - anchor).days // 7) % 2
            excluded = current.strftime('%d.%m.%Y') in template['_exclude']
            monthly = not template['_last_month_weekday'] or (current + timedelta(days=7)).month != current.month
            if not excluded and monthly and (not template['week'] or (template['week'] == 'odd' and parity == 0) or (template['week'] == 'even' and parity == 1)):
                rows.append({key: value for key, value in template.items() if not key.startswith('_')} | {'date': current.isoformat()})
            current += timedelta(days=7)
    if len(rows) > MAX_ROWS:
        raise ValueError('В одном импорте допускается не больше 6000 занятий. Сократите период.')
    if not rows and not errors:
        errors.append({'row': 1, 'message': 'Занятия не найдены. Проверьте чёткость фото, группу и выбранный период.'})
    if any(grid.ocr for grid in grids):
        warnings.insert(0, 'Фото распознано автоматически. Проверьте названия, время, преподавателей и аудитории перед сохранением.')
    if any(row['group'] for row in templates):
        warnings.append('В таблице есть языковые подгруппы. Выберите свои варианты перед сохранением или настройте подгруппы в профиле для общего расписания.')
    return {'format': 'table', 'sheets': [], 'columns': [], 'mapping': {}, 'rows': rows,
            'templates': [{key: value for key, value in row.items() if not key.startswith('_')} for row in templates],
            'errors': errors[:50], 'error_count': len(errors), 'warnings': list(dict.fromkeys(warnings)),
            'table_groups': sorted(detected_groups), 'selected_group': selected,
            'period': {'from': first.isoformat(), 'to': last.isoformat(), 'week_anchor': anchor.isoformat()},
            'ocr': any(grid.ocr for grid in grids)}
