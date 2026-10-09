"""Private time corrections, shared by the diary and reminder workers."""
from database import get_db, get_setting


def initialize(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS lesson_times(
        owner TEXT NOT NULL,group_id TEXT NOT NULL,lesson_id TEXT NOT NULL,
        start TEXT NOT NULL,end TEXT NOT NULL,
        PRIMARY KEY(owner,group_id,lesson_id))''')


def for_owner(owner):
    c = get_db()
    try:
        with c:
            initialize(c)
        return {row['lesson_id']: (row['start'], row['end']) for row in c.execute(
            'SELECT lesson_id,start,end FROM lesson_times WHERE owner=? AND group_id=?',
            (owner, get_setting('group_id')))}
    finally:
        c.close()


def initialize_rooms(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS lesson_rooms(
        owner TEXT NOT NULL,group_id TEXT NOT NULL,lesson_id TEXT NOT NULL,
        room TEXT NOT NULL,PRIMARY KEY(owner,group_id,lesson_id))''')


def rooms_for_owner(owner):
    c=get_db()
    try:
        with c:initialize_rooms(c)
        return {row['lesson_id']:row['room'] for row in c.execute(
            'SELECT lesson_id,room FROM lesson_rooms WHERE owner=? AND group_id=?',
            (owner,get_setting('group_id')))}
    finally:c.close()
