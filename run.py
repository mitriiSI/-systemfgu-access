import os
import threading
from database import init_db

# Route modules need the base tables during import, including on a fresh server.
init_db()

from app import create_app
from bot.worker import start_bot_worker

app = create_app()

if __name__ == '__main__':
    # Запуск бота в отдельном фоновом потоке
    threading.Thread(target=start_bot_worker, daemon=True, name="BotWorker").start()

    port = int(os.getenv('PORT', 5000))
    print(f"Сервер дневника запущен на http://0.0.0.0:{port}", flush=True)
    from waitress import serve
    serve(app,host='0.0.0.0',port=port,threads=8,connection_limit=64,backlog=64,
          max_request_body_size=100*1024*1024,channel_timeout=60,expose_tracebacks=False,
          clear_untrusted_proxy_headers=False)
