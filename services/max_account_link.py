"""A typed Telegram ID identifies the approver; it never grants access on its own."""
import hashlib,secrets,time
from config import ADMIN_IDS
from database import central_db
from services import max_platform

def initialize():
    with central_db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS max_account_links(max_id INTEGER PRIMARY KEY,tg_id INTEGER NOT NULL,token_hash TEXT UNIQUE NOT NULL,expires REAL NOT NULL,created REAL NOT NULL)')
        c.execute('DELETE FROM max_account_links WHERE expires<?',(time.time(),))
def owner_for_telegram(c,tg):
    if tg in ADMIN_IDS:owner='admin:'+str(tg)
    else:
        member=c.execute('SELECT code FROM members WHERE tg=? AND active=1',(tg,)).fetchone();owner='member:'+member[0] if member else None
    return owner if owner and max_platform.member_for_owner(owner) else None
def request_link(max_id,tg):
    initialize();max_platform.valid_user_id(max_id);max_platform.valid_user_id(tg);stamp=time.time();token=secrets.token_urlsafe(24)
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM max_identities WHERE user_id=?',(max_id,)).fetchone():return 'Ваш MAX уже подключён. Откройте дневник.'
        attempt=c.execute('SELECT * FROM max_attempts WHERE user_id=?',(max_id,)).fetchone()
        if attempt and attempt['until']>stamp and attempt['count']>=5:return 'Слишком много попыток. Попробуйте через 15 минут.'
        count=attempt['count']+1 if attempt and attempt['until']>stamp else 1
        c.execute('INSERT OR REPLACE INTO max_attempts VALUES(?,?,?)',(max_id,count,attempt['until'] if attempt and attempt['until']>stamp else stamp+900))
        if not owner_for_telegram(c,tg):return 'Аккаунт не найден. Проверьте Telegram ID командой /myid в Telegram. Новый аккаунт создаётся командой /register по приглашению.'
        previous=c.execute('SELECT created FROM max_account_links WHERE tg_id=? AND expires>?',(tg,stamp)).fetchone()
        if previous and stamp-previous['created']<60:return 'Подтверждение уже отправлено в Telegram. Проверьте сообщения бота.'
        c.execute('INSERT OR REPLACE INTO max_account_links VALUES(?,?,?,?,?)',(max_id,tg,hashlib.sha256(token.encode()).hexdigest(),stamp+300,stamp))
    from services.telegram import tg_call
    from services.bot_context import messenger
    try:
        with messenger(None):tg_call('sendMessage',chat_id=tg,text='Подключить MAX к вашему аккаунту Midiary?\nMAX ID: '+str(max_id)+'\nПодтвердите, только если сами начали привязку. Данные и права будут общими. Запрос действует 5 минут.',reply_markup={'inline_keyboard':[[{'text':'Подключить MAX','callback_data':'maxlink:yes:'+token},{'text':'Отклонить','callback_data':'maxlink:no:'+token}]]})
    except Exception:
        with central_db() as c:c.execute('DELETE FROM max_account_links WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        return 'Не удалось доставить подтверждение в Telegram. Откройте там бота и отправьте /start, затем повторите привязку.'
    return 'Подтверждение отправлено в Telegram. Нажмите «Подключить MAX» в сообщении бота, затем вернитесь в MAX.'
def confirm(callback):
    initialize();tg=callback['from']['id'];message=callback.get('message',{})
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg:return
    parts=callback.get('data','').split(':',2)
    if len(parts)!=3 or parts[1] not in ('yes','no'):return
    digest=hashlib.sha256(parts[2].encode()).hexdigest();linked=None;text='Запрос истёк или у аккаунта нет доступа.'
    with central_db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM max_account_links WHERE token_hash=? AND tg_id=? AND expires>?',(digest,tg,time.time())).fetchone()
        if row:
            owner=owner_for_telegram(c,tg)
            if parts[1]=='no':text='Привязка MAX отклонена.'
            elif owner:
                try:
                    max_platform.bind(c,row['max_id'],owner);c.execute('DELETE FROM settings WHERE key=?',('max_delivery_disabled:'+owner,));linked=(row['max_id'],owner);text='MAX подключён к вашему аккаунту Midiary. Данные и права общие с Telegram.'
                except PermissionError:text='MAX уже привязан к другому аккаунту. Ничего не изменено.'
            c.execute('DELETE FROM max_account_links WHERE token_hash=?',(digest,))
    from services.telegram import tg_call
    tg_call('answerCallbackQuery',callback_query_id=callback['id'],text=text[:200])
    tg_call('editMessageText',chat_id=tg,message_id=message['message_id'],text=text)
    if linked:max_platform.send_telegram('sendMessage',{'text':'MAX подключён. Теперь можно подтвердить вход или открыть дневник.','reply_markup':{'inline_keyboard':[[{'text':'Открыть дневник','web_app':{'url':max_platform.get_public_url()}}]]}},user_id=linked[0],owner=linked[1])
