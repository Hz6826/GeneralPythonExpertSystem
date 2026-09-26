# ./app/__init__.py
import json

from flask import Flask

from app.route import simple_frontend_bp, api_v1_bp


def create_app(config_file="config.json", enable_simple_frontend=True):
    app = Flask(__name__)
    app.config.from_file(config_file, load=json.load)

    if enable_simple_frontend:
        app.register_blueprint(simple_frontend_bp)
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")

    return app
