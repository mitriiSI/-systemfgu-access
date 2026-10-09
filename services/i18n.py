import json,re
from functools import lru_cache
from pathlib import Path
from database import central_setting,central_db
from config import ROOT_DIR,ADMIN_IDS

@lru_cache(maxsize=1)
def dictionary():return json.loads((ROOT_DIR/'static/translations.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def translation_pattern():
    return re.compile('|'.join(re.escape(k) for k in sorted(dictionary(),key=len,reverse=True) if len(k)>=2))

def transliterate_name(name):
    letters=dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',('a','b','v','g','d','e','yo','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','kh','ts','ch','sh','shch','','y','','e','yu','ya')))
    return ''.join((letters[c.lower()].capitalize() if c.isupper() else letters[c.lower()]) if c.lower() in letters else c for c in name)

def translate(text,language):
    if language=='ru' or not isinstance(text,str):return text
    values=dictionary();index=0 if language=='en' else 1
    stripped=text.strip()
    if stripped in values:return text.replace(stripped,values[stripped][index])
    def replacement(match):
        value=match.group();start,end=match.span()
        if re.search('[А-Яа-яЁё]',value[:1]) and re.search('[А-Яа-яЁё]',text[max(0,start-1):start]):return value
        if re.search('[А-Яа-яЁё]',value[-1:]) and re.search('[А-Яа-яЁё]',text[end:end+1]):return value
        return values[value][index]
    rendered=translation_pattern().sub(replacement,text)
    if re.search('[А-Яа-яЁё]',rendered):
        from services.content_translation import notification_text
        translated=notification_text(text,language)
        if translated!=text:return translated
    return rendered

def owner_language(owner):return central_setting('language_'+owner,'ru')

def telegram_language(tg):
    if tg in ADMIN_IDS:return owner_language('admin:'+str(tg))
    with central_db() as c:row=c.execute('SELECT code FROM members WHERE tg=?',(tg,)).fetchone()
    return owner_language('member:'+row[0]) if row else 'ru'

def translate_payload(payload,language):
    from services.group_comparison import COMMON_NOTICE
    value=dict(payload)
    for key in ('text','title','body'):
        if key in value:
            text=value[key]
            # Keep the account's explicitly requested notice verbatim in every channel.
            value[key]=COMMON_NOTICE.join(translate(part,language) for part in text.split(COMMON_NOTICE)) if isinstance(text,str) else text
    if isinstance(value.get('reply_markup'),dict):
        value['reply_markup']=dict(value['reply_markup'])
        if 'inline_keyboard' in value['reply_markup']:value['reply_markup']['inline_keyboard']=[[dict(button,text=translate(button.get('text',''),language)) for button in row] for row in value['reply_markup']['inline_keyboard']]
    return value
