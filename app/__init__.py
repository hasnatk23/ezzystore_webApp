from datetime import datetime, date, time
from flask import Flask
from .config import Config
from .db import get_db, close_db
from .models import init_models
from .auth import auth_bp
from .admin.routes import admin_bp
from .manager.routes import manager_bp


def _to_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed
            except ValueError:
                continue
    return None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize DB + tables + default admin once, at startup
    with app.app_context():
        db = get_db()
        init_models(db)
        db.commit()

    app.teardown_appcontext(close_db)

    @app.template_filter("human_datetime")
    def human_datetime(value, fmt="%d-%b-%Y - %I:%M %p"):
        dt = _to_datetime(value)
        if not dt:
            return value or "—"
        return dt.strftime(fmt)

    @app.template_filter("human_date")
    def human_date(value, fmt="%d-%b-%Y"):
        dt = _to_datetime(value)
        if not dt:
            return value or "—"
        return dt.strftime(fmt)
    @app.template_filter("human_time")
    def human_time(value, fmt="%I:%M %p"):
        dt = _to_datetime(value)
        if not dt:
            return value or "—"
        return dt.strftime(fmt)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(manager_bp, url_prefix="/manager")

    return app
