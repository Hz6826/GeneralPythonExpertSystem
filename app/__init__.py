# ./app/__init__.py
import json
import locale

from flask import Flask

from app.route import simple_frontend_bp, api_v1_bp, register_error_handlers


def load_config(handle):
    """读取配置文件，兼容各种编码。

    Flask 默认用「文本模式 + 本地编码」打开配置文件，中文 Windows 上是 GBK，
    于是 UTF-8 写的配置（只要带中文）和 `echo {} > config.json` 产生的 UTF-16
    都会直接 UnicodeDecodeError。这里改成读原始字节：

      1. 先按 JSON 标准来 —— json 会依据 BOM / 空字节自行识别 UTF-8/16/32；
      2. 再退回本地编码，照顾以前用记事本「ANSI」存下来的旧配置。
    """
    raw = handle.read()
    if isinstance(raw, str):                     # 万一传进来的是文本句柄
        return json.loads(raw)
    try:
        return json.loads(raw)
    except UnicodeDecodeError:
        return json.loads(raw.decode(locale.getpreferredencoding(False)))


def create_app(config_file="config.json", enable_simple_frontend=True):
    app = Flask(__name__)

    # 配置文件是可选的：app/config.json 被 gitignore，克隆下来本来就没有。
    #   silent=True → 文件不存在时用默认值，不再抛 FileNotFoundError；
    #   text=False  → 以二进制模式打开，配合 load_config 做编码兼容。
    app.config.from_file(config_file, load=load_config, silent=True, text=False)

    # 未注册的 /api/v1/* 路径也要返回 JSON 信封
    register_error_handlers(app)

    if enable_simple_frontend:
        app.register_blueprint(simple_frontend_bp)
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")

    return app
