from dotenv import load_dotenv
load_dotenv()
import os
import re
from datetime import timedelta, timezone
from pathlib import Path

# Корневая папка и пути к данным
ROOT_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv('DATA_DIR', ROOT_DIR / 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR = DATA_DIR / 'files'
FILES_DIR.mkdir(exist_ok=True)

# Секреты и токены из .env
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
PRIMARY_ADMIN_ID = int(os.getenv('PRIMARY_ADMIN_ID', '0'))
ADMIN_IDS = {PRIMARY_ADMIN_ID}
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://localhost:5000').rstrip('/')
SESSION_SECRET = os.getenv('SESSION_SECRET', '')
if len(SESSION_SECRET) < 32 or SESSION_SECRET == 'local_dev_secret_key_1234567890_min_32_chars':
    raise RuntimeError('Set a random SESSION_SECRET of at least 32 characters before starting Midiary.')

# Часовой пояс
MOSCOW_TZ = timezone(timedelta(hours=3))
REMINDER_CHOICES = (5, 10, 15, 30, 45, 60, 90, 120)

def get_public_url() -> str:
    return PUBLIC_URL
