"""Authenticated website visits and an administrator's notification overview."""
import json
import time
from datetime import datetime
from flask import Blueprint, abort, jsonify
from config import ADMIN_IDS, MOSCOW_TZ
from database import central_db

usage_bp = Blueprint('user_usage', __name__)

def initialize():
    with central_db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS account_activity(owner TEXT PRIMARY KEY,last_seen REAL NOT NULL)')
        c.execute("INSERT OR IGNORE INTO settings VALUES('activity_tracking_since',?)", (str(time.time()),))

def touch(owner):
    stamp = time.time()
    with central_db() as c:
        c.execute('''INSERT INTO account_activity VALUES(?,?) ON CONFLICT(owner)
            DO UPDATE SET last_seen=excluded.last_seen WHERE account_activity.last_seen<?''', (owner, stamp, stamp-30))

@usage_bp.get('/api/admin/users')
def users():
    from routes.auth import get_current_member
    if not get_current_member()['admin']:
        abort(403)
    now = time.time()
    today = datetime.fromtimestamp(now, MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with central_db() as c:
        rows = [dict(row) for row in c.execute('''SELECT m.code,m.name,m.tg,m.active,p.faculty,p.group_id,g.name AS group_name
            FROM members m LEFT JOIN university_profiles p ON p.owner='member:'||m.code
            LEFT JOIN university_groups g ON g.id=p.group_id ORDER BY m.name COLLATE NOCASE''')]
        profiles = {row['owner']: dict(row) for row in c.execute('''SELECT p.owner,p.faculty,p.group_id,g.name AS group_name
            FROM university_profiles p LEFT JOIN university_groups g ON g.id=p.group_id WHERE p.owner LIKE 'admin:%' ''')}
        activity = dict(c.execute('SELECT owner,last_seen FROM account_activity'))
        settings = dict(c.execute("SELECT key,value FROM settings WHERE key LIKE 'midiary_offsets:%:notification-channels' OR key LIKE 'max_delivery_disabled:%' OR key LIKE 'privacy_broadcast_%' OR key='activity_tracking_since'"))
        max_owners = {row[0] for row in c.execute('SELECT owner FROM max_identities')}
        devices = dict(c.execute('SELECT owner,count(*) FROM web_push_devices GROUP BY owner'))
        deleting = {row[0] for row in c.execute("SELECT owner FROM privacy_deletions WHERE kind='account'")}
    accounts = []
    for row in rows:
        if row['tg'] in ADMIN_IDS:
            continue
        owner = 'member:'+row.pop('code')
        accounts.append((owner,row,False))
    for index, ident in enumerate(sorted(ADMIN_IDS),1):
        owner = 'admin:'+str(ident)
        accounts.append((owner,{'name':'Администратор '+str(index),'tg':ident,'active':1,**profiles.get(owner,{})},True))
    result = []
    for owner,row,admin in accounts:
        if owner in deleting:
            continue
        enabled = bool(row['active'])
        last_seen = activity.get(owner)
        try:
            choices = json.loads(settings.get('midiary_offsets:'+owner+':notification-channels','{}'))
        except (ValueError,TypeError):
            choices = {}
        if not isinstance(choices,dict):
            choices = {}
        connected = {'telegram':row.get('tg') is not None,'max':owner in max_owners,'website':devices.get(owner,0)>0}
        channels = {}
        for channel in connected:
            selected = choices.get(channel,True) is True
            blocked = channel=='max' and settings.get('max_delivery_disabled:'+owner)=='1'
            channels[channel] = {'enabled':selected,'connected':connected[channel],
                'available':enabled and selected and connected[channel] and not blocked,'blocked':blocked}
        result.append({'name':row['name'],'admin':admin,'account_enabled':enabled,'faculty':row.get('faculty'),
            'group_id':row.get('group_id'),'group_name':row.get('group_name'),'last_seen':last_seen,
            'online':enabled and last_seen is not None and now-300<=last_seen<=now+1,
            'active_today':enabled and last_seen is not None and today<=last_seen<=now+1,
            'active_week':enabled and last_seen is not None and now-7*86400<=last_seen<=now+1,
            'channels':channels,'website_devices':devices.get(owner,0),
            'announcements':settings.get('privacy_broadcast_'+owner,'1')=='1'})
    return jsonify(users=result,counts={'total':len(result),'online':sum(row['online'] for row in result),
        'today':sum(row['active_today'] for row in result),'week':sum(row['active_week'] for row in result)},
        tracking_since=float(settings.get('activity_tracking_since',now)),updated=now)
