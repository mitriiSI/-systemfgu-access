from services.telegram import tg_call
from services.notification_channels import preferences,save,CHANNELS
def menu(tg,message_id=None):
    from bot.handlers import bot_member
    user=bot_member(tg)
    if not user:return tg_call('sendMessage',chat_id=tg,text='Сначала привяжите аккаунт Midiary командой /link и своим кодом.')
    values=preferences(user['owner']);labels={'telegram':'Telegram','max':'MAX','website':'Уведомления сайта'}
    data={'chat_id':tg,'text':'Куда присылать уведомления\nВыбор действует для пар, дедлайнов и ДЗ на завтра. Общие объявления настраиваются отдельно.','reply_markup':{'inline_keyboard':[[{'text':('✓ ' if values[key] else '○ ')+labels[key],'callback_data':'channels:'+key}] for key in CHANNELS]}}
    if message_id is not None:data['message_id']=message_id
    return tg_call('editMessageText' if message_id is not None else 'sendMessage',**data)
def callback(value):
    from bot.handlers import bot_member
    tg=value['from']['id'];message=value.get('message',{});user=bot_member(tg)
    if message.get('chat',{}).get('type')!='private' or message['chat']['id']!=tg or not user:return
    choice=value.get('data','').partition(':')[2]
    if choice!='menu':
        if choice not in CHANNELS:return
        prefs=preferences(user['owner']);prefs[choice]=not prefs[choice];save(user['owner'],prefs)
    tg_call('answerCallbackQuery',callback_query_id=value['id'],text='Настройки сохранены')
    return menu(tg,message['message_id'])
