"""Per-account destinations for class, deadline and homework reminders."""
import json
from database import central_setting,central_set_setting
CHANNELS=('telegram','max','website')
def preferences(owner):
    try:value=json.loads(central_setting('midiary_offsets:'+owner+':notification-channels','{}'))
    except (ValueError,TypeError):value={}
    return {channel:value.get(channel,True) is True for channel in CHANNELS} if isinstance(value,dict) else dict.fromkeys(CHANNELS,True)
def enabled(owner,channel):return preferences(owner).get(channel,False)
def save(owner,value):
    if not isinstance(value,dict) or set(value)!=set(CHANNELS) or any(type(v) is not bool for v in value.values()):raise ValueError('Invalid notification channels')
    central_set_setting('midiary_offsets:'+owner+':notification-channels',json.dumps(value));return value
