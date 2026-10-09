from datetime import timedelta
from flask import Flask, send_from_directory, jsonify
from config import ROOT_DIR, SESSION_SECRET
from routes.auth import auth_bp
from routes.materials import materials_bp
from routes.schedule import schedule_bp
from routes.university import university_bp
from routes.imports import imports_bp


def create_app():
    app = Flask(__name__, static_folder=str(ROOT_DIR / 'static'), template_folder=str(ROOT_DIR / 'templates'))
    app.secret_key = SESSION_SECRET
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='None',
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=256 * 1024,
        MAX_FORM_PARTS=32,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    from services.security import configure
    configure(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(university_bp)
    app.register_blueprint(imports_bp)
    from services.group_comparison import comparison_bp,initialize as initialize_comparison
    initialize_comparison()
    app.register_blueprint(comparison_bp)

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/sw.js')
    def sw():
        return send_from_directory(app.static_folder, 'sw.js')

    def error(exc):
        messages = {400: 'Проверьте введённые данные', 401: 'Войдите заново по коду доступа',
                    403: 'Нет доступа', 404: 'Не найдено', 409: 'Данные уже существуют',
                    413: 'Максимальный размер файла — 100 МБ', 429: 'Слишком много попыток. Попробуйте позже.',
                    503: 'Администратор ещё не заполнил сведения о владельце сервиса. Регистрация временно недоступна.'}
        return jsonify(error=messages.get(exc.code, 'Ошибка')), exc.code

    for status in (400, 401, 403, 404, 405, 409, 413, 415, 429, 503):
        app.register_error_handler(status, error)
    from services.midiary import midiary_bp
    app.register_blueprint(midiary_bp)
    from services.admissions import initialize as initialize_admissions
    initialize_admissions()
    from services.support import support_bp,initialize as initialize_support
    initialize_support()
    app.register_blueprint(support_bp)
    from services.subscriptions import subscriptions_bp,initialize as initialize_subscriptions
    initialize_subscriptions()
    app.register_blueprint(subscriptions_bp)
    from services.lesson_history import history_bp
    app.register_blueprint(history_bp)
    from services.history_points import points_bp, initialize as initialize_points
    initialize_points()
    app.register_blueprint(points_bp)
    from services.content_translation import translation_bp
    app.register_blueprint(translation_bp)
    from services.legal import legal_bp
    from services.privacy import privacy_bp, initialize
    initialize()
    app.register_blueprint(legal_bp)
    app.register_blueprint(privacy_bp)
    from services.max_platform import initialize as initialize_max
    from routes.max_app import max_bp
    initialize_max()
    from services.bot_registration import initialize as initialize_registration
    from services.max_account_link import initialize as initialize_links
    initialize_registration();initialize_links()
    app.register_blueprint(max_bp)
    from services.user_activity import initialize as initialize_activity, usage_bp
    initialize_activity()
    app.register_blueprint(usage_bp)
    from services.channel_bridge import initialize as initialize_bridge, bridge_bp
    initialize_bridge()
    app.register_blueprint(bridge_bp)
    return app
