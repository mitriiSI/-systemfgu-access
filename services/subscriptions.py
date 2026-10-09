"""Future subscription prices and personal grants; payments and gating are disabled."""
import time
from datetime import date, datetime, time as day_time
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, jsonify, request

from config import MOSCOW_TZ
from database import central_db, utc_now
from services.admissions import administrator

subscriptions_bp = Blueprint('subscriptions', __name__)
MAX_PRICE = 100000000


def initialize():
    with central_db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS subscription_settings(id INTEGER PRIMARY KEY CHECK(id=1),base_price INTEGER);
        INSERT OR IGNORE INTO subscription_settings VALUES(1,NULL);
        CREATE TABLE IF NOT EXISTS subscription_overrides(owner TEXT PRIMARY KEY,price INTEGER,free INTEGER NOT NULL,
            free_until REAL,updated TEXT NOT NULL,admin TEXT NOT NULL);
        ''')


def price(value, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_PRICE:
        raise ValueError('Укажите цену от 0 до 1000000 рублей с точностью до копейки.')
    return value


def rubles(value):
    try:
        if not isinstance(value,str) or len(value)>32:raise ValueError()
        number = Decimal(value.replace(',', '.'))
        if not number.is_finite() or not 0 <= number <= MAX_PRICE / 100 or number.as_tuple().exponent < -2:
            raise ValueError()
        return price(int(number * 100))
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError('Укажите цену в рублях, например 199 или 99.50.') from None


def set_base(owner, value):
    administrator(owner)
    value = price(value, nullable=True)
    initialize()
    with central_db() as c:
        c.execute('UPDATE subscription_settings SET base_price=? WHERE id=1', (value,))


def set_override(owner, code, *, personal_price=None, free=False, free_until=None, reset=False):
    administrator(owner)
    personal_price = price(personal_price, nullable=True)
    if type(free) is not bool or type(reset) is not bool:
        raise ValueError('Проверьте параметры доступа.')
    if free_until is not None:
        if not free or type(free_until) not in (int, float) or not time.time() < free_until < time.time() + 36600 * 86400:
            raise ValueError('Укажите будущую дату окончания бесплатного доступа.')
    initialize()
    target = 'member:' + code
    with central_db() as c:
        row = c.execute("SELECT p.faculty FROM members m JOIN university_profiles p ON p.owner='member:'||m.code WHERE m.code=?", (code,)).fetchone()
        if not row:
            raise ValueError('Участник не найден.')
        if row['faculty'] == 'fgu':
            raise ValueError('Для ФГУ доступ всегда бесплатный.')
        base = c.execute('SELECT base_price FROM subscription_settings WHERE id=1').fetchone()[0]
        if base is not None and personal_price is not None and personal_price > base:
            raise ValueError('Персональная цена не должна превышать базовую.')
        if reset:
            c.execute('DELETE FROM subscription_overrides WHERE owner=?', (target,))
        else:
            c.execute('INSERT OR REPLACE INTO subscription_overrides VALUES(?,?,?,?,?,?)', (target, personal_price, int(free), free_until, utc_now(), owner))


def status(owner):
    initialize()
    with central_db() as c:
        profile = c.execute('SELECT faculty FROM university_profiles WHERE owner=?', (owner,)).fetchone()
        override = c.execute('SELECT * FROM subscription_overrides WHERE owner=?', (owner,)).fetchone()
        base = c.execute('SELECT base_price FROM subscription_settings WHERE id=1').fetchone()[0]
    faculty = profile['faculty'] if profile else None
    exempt = owner.startswith('admin:') or faculty == 'fgu'
    active_free = bool(override and override['free'] and (override['free_until'] is None or override['free_until'] > time.time()))
    personal = override['price'] if override else None
    effective = base if personal is None else (personal if base is None else min(base, personal))
    mode = 'fgu_free' if faculty == 'fgu' else 'admin_free' if owner.startswith('admin:') else 'personal_free' if active_free or effective == 0 else 'planned'
    return {'faculty': faculty, 'exempt': exempt, 'mode': mode, 'price': 0 if exempt or active_free else effective,
            'base_price': base, 'personal_price': personal, 'free': bool(override and override['free']),
            'free_until': override['free_until'] if override else None, 'has_override': bool(override),
            'currency': 'RUB', 'period': 'month', 'payments_enabled': False, 'access_allowed': True}


def text(owner):
    value = status(owner)
    if value['mode'] == 'fgu_free':
        return 'ФГУ — бесплатный доступ. Оплата не требуется.'
    if value['mode'] == 'admin_free':
        return 'Для администратора доступ бесплатный.'
    if value['mode'] == 'personal_free':
        return 'Вам назначен бесплатный доступ. Приём платежей ещё не включён.'
    cost = 'Цена пока не установлена.' if value['price'] is None else 'Ваша будущая цена: ' + format(Decimal(value['price']) / 100, '.2f') + ' ₽ в месяц.'
    return 'Подписка готовится. ' + cost + ' Сейчас все функции доступны, платежи не принимаются.'


@subscriptions_bp.get('/api/subscription')
def personal():
    from routes.auth import get_personal_owner
    return jsonify(status(get_personal_owner()))


@subscriptions_bp.route('/api/admin/subscriptions', methods=['GET', 'POST'])
def manage():
    from routes.auth import get_personal_owner, get_current_member
    if not get_current_member()['admin']:
        abort(403)
    initialize()
    if request.method == 'POST':
        body = request.get_json() or {}
        try:
            if 'base_price' in body:
                set_base(get_personal_owner(), body['base_price'])
            else:
                if not isinstance(body.get('member'), str):
                    raise ValueError('Выберите участника.')
                until = body.get('free_until')
                if isinstance(until, str):
                    until = datetime.combine(date.fromisoformat(until), day_time.max, MOSCOW_TZ).timestamp()
                set_override(get_personal_owner(), body['member'], personal_price=body.get('price'),
                             free=body.get('free', False), free_until=until, reset=body.get('reset', False))
        except (ValueError, TypeError, OverflowError) as error:
            return jsonify(error=str(error)), 400
    with central_db() as c:
        base = c.execute('SELECT base_price FROM subscription_settings WHERE id=1').fetchone()[0]
        rows = [dict(r) for r in c.execute("SELECT m.code AS id,m.name,m.tg,p.faculty FROM members m JOIN university_profiles p ON p.owner='member:'||m.code WHERE p.faculty<>'fgu' ORDER BY m.name")]
    for member in rows:
        member['subscription'] = status('member:' + member['id'])
    return jsonify(base_price=base, currency='RUB', payments_enabled=False, members=rows)
