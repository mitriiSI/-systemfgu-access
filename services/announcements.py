"""One administrator action queues both messenger deliveries in one transaction."""
import time
from config import ADMIN_IDS

def queue(connection,owner,origin,message_id,text):
    if not owner.startswith('admin:') or int(owner[6:]) not in ADMIN_IDS:raise PermissionError('Administrator required')
    if origin not in ('telegram','max'):raise ValueError('Invalid announcement origin')
    admin=int(owner[6:]);tg_id=message_id if origin=='telegram' else 'max:'+str(message_id)
    max_id='tg:'+str(message_id) if origin=='telegram' else str(message_id)
    row=connection.execute('SELECT id FROM broadcasts WHERE admin=? AND message_id=?',(admin,tg_id)).fetchone()
    if row:tg_job=row['id']
    else:
        unlinked=connection.execute('SELECT count(*) FROM members WHERE active=1 AND (tg IS NULL OR tg<=0)').fetchone()[0]
        tg_job=connection.execute('INSERT INTO broadcasts(admin,message_id,body,created,unlinked) VALUES(?,?,?,?,?)',(admin,tg_id,text,time.time(),unlinked)).lastrowid
        connection.execute('INSERT INTO broadcast_deliveries(job,tg,recipient_owner) SELECT ?,tg,min(?||code) FROM members WHERE active=1 AND tg>0 GROUP BY tg',(tg_job,'member:'))
    row=connection.execute('SELECT id FROM max_broadcasts WHERE owner=? AND message_id=?',(owner,max_id)).fetchone()
    if row:max_job=row['id']
    else:
        max_job=connection.execute('INSERT INTO max_broadcasts(owner,message_id,body,created) VALUES(?,?,?,?)',(owner,max_id,text,time.time())).lastrowid
        connection.execute('INSERT INTO max_broadcast_deliveries(job,user_id,recipient_owner) SELECT ?,i.user_id,i.owner FROM max_identities i JOIN members m ON i.owner=?||m.code WHERE m.active=1',(max_job,'member:'))
    return tg_job,max_job

def paired_summary(tg_job,max_job):
    from bot.broadcast import summary
    from bot.max_worker import broadcast_summary
    return 'Telegram\n'+summary(tg_job)+'\n\n'+broadcast_summary(max_job)
