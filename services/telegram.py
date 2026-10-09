"""Telegram transport with safe, actionable API errors."""
import re
import requests
from config import BOT_TOKEN


class TelegramAPIError(RuntimeError):
    def __init__(self, method, status, description):
        self.method = method
        self.code = status
        safe = str(description).replace(BOT_TOKEN, '[BOT_TOKEN]') if BOT_TOKEN else str(description)
        safe = re.sub(r'https?://\S+', '[URL]', safe)
        self.description = safe[:300]
        super().__init__('Telegram ' + method + ': ' + str(status) + ' ' + self.description)


def tg_call(method, **data):
    from services.bot_context import current
    context=current.get()
    if context and context['platform']=='max':
        from services.max_platform import compatibility
        return compatibility(method,data)
    if not BOT_TOKEN:
        raise RuntimeError('BOT_TOKEN is not configured')
    user_content=data.pop('_midiary_user_content',False)
    if not user_content and isinstance(data.get('chat_id'),int):
        from services.i18n import telegram_language,translate_payload
        data=translate_payload(data,telegram_language(data['chat_id']))
    response = requests.post('https://api.telegram.org/bot' + BOT_TOKEN + '/' + method,
                             json=data, timeout=35)
    try:
        result = response.json()
    except ValueError:
        raise TelegramAPIError(method, response.status_code, 'Non-JSON response') from None
    if response.status_code >= 400 or not result.get('ok'):
        status = result.get('error_code', response.status_code)
        description = result.get('description', 'Request rejected')
        # An idempotent callback retry can try to display the same text again.
        if (method in ('editMessageText', 'editMessageReplyMarkup') and status == 400
                and 'message is not modified' in str(description).lower()):
            return True
        raise TelegramAPIError(method, status, description)
    return result['result']
