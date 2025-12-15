from flask import Flask
from .config import Config
from .db import get_db, close_db
from .models import init_models
from .auth import auth_bp
from .admin.routes import admin_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize DB + tables + default admin once, at startup
    with app.app_context():
        db = get_db()
        init_models(db)
        db.commit()

    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app
