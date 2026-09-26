# ./app/route.py
import functools

import flask
from flask import Blueprint, render_template, jsonify, Response, request
from werkzeug.exceptions import HTTPException, BadRequest, NotFound
import logging

import example, core
from core.model import Fact

simple_frontend_bp = Blueprint('main', __name__)
api_v1_bp = Blueprint('api_v1', __name__)

DEFAULT_SUCCESS_TEMPLATE: dict[str, int | str | None | dict] = {
    "code": 0,
    "status": "success",
    "data": {}
}

DEFAULT_ERROR_TEMPLATE: dict[str, int | str | None] = {
    "code": -1,
    "status": "error",
    "message": "Unknown error"
}


def auto_handle_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            res = func(*args, **kwargs)
            if isinstance(res, dict):
                success_dict = DEFAULT_SUCCESS_TEMPLATE.copy()
                success_dict["data"] = res
                return jsonify(success_dict)
            if isinstance(res, Response) or (isinstance(res, tuple) and isinstance(res[0], Response)):
                return res
            raise TypeError(f"Unsupported return type: {type(res)}")
        except HTTPException as e:
            error_dict = DEFAULT_ERROR_TEMPLATE.copy()
            error_dict["code"] = e.code
            error_dict["message"] = e.description
            return jsonify(error_dict), e.code
        except Exception as e:
            error_dict = DEFAULT_ERROR_TEMPLATE.copy()
            if flask.current_app.debug:
                error_dict["message"] = str(e)
            logging.exception("Unhandled exception in %s", func.__name__)
            return jsonify(error_dict), 500

    return wrapper


# ---------------- 前端 ----------------

@simple_frontend_bp.route("/")
def index():
    return render_template("index.html")


# ---------------- API v1 ----------------

@api_v1_bp.route("/")
@auto_handle_exception
def ping():
    return {}


# ---- example ----

@api_v1_bp.route("/example/list", methods=["GET"])
@auto_handle_exception
def list_example():
    return {"list": example.get_list()}


@api_v1_bp.route("/example/load", methods=["POST"])
@auto_handle_exception
def load_example():
    name = request.args.get("name")
    if not name:
        raise BadRequest("Missing required query parameter: name")
    if not example.has(name):
        raise NotFound(f"Example not found: {name}")
    core.engine().load_kb(example.get(name).get_kb())
    return {}


# ---- engine ----

@api_v1_bp.route("/engine/init", methods=["POST"])
@auto_handle_exception
def init_engine():
    core.engine().init()
    return {}


@api_v1_bp.route("/engine/reset", methods=["POST"])
@auto_handle_exception
def reset_engine():
    core.engine().reset()
    return {}


@api_v1_bp.route("/engine/run", methods=["POST"])
@auto_handle_exception
def run_engine():
    if not core.engine().run_in_background():
        raise RuntimeError("Engine is running!")
    return {}


@api_v1_bp.route("/engine/pause", methods=["POST"])
@auto_handle_exception
def pause_engine():
    if not core.engine().pause():
        raise RuntimeError("Engine is not running!")
    return {}


@api_v1_bp.route("/engine/status", methods=["POST"])
@auto_handle_exception
def engine_status():
    eng = core.engine()
    return {
        "running": eng.running,
        "iterations": eng.iterations,
        "stop_reason": eng.stop_reason,
        "reached_max_iterations": eng.reached_max_iterations,
    }


@api_v1_bp.route("/engine/step", methods=["POST"])
@auto_handle_exception
def step_engine():
    eng = core.engine()
    rule = eng.step()
    if rule is None:
        # 已停止（no_rule / no_change / max_iter）或无规则可触发
        return {
            "fired": False,
            "stop_reason": eng.stop_reason,
            "iterations": eng.iterations,
        }
    return {
        "fired": True,
        "name": rule.name,
        "conditions": rule.conditions,
        "conclusion": rule.conclusion,
        "priority": rule.priority,
        "iterations": eng.iterations,
    }


def _fact_to_dict(fact: Fact) -> dict:
    return {"name": fact.name, "value": fact.value}


@api_v1_bp.route("/engine/facts", methods=["GET"])
@auto_handle_exception
def list_facts():
    return {"facts": [_fact_to_dict(f) for f in core.engine().get_facts()]}


@api_v1_bp.route("/engine/facts", methods=["POST"])
@auto_handle_exception
def add_fact():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object")

    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise BadRequest("Field 'name' must be a non-empty string")

    value = body.get("value", True)
    try:
        hash(value)          # Fact 会被放进 set，value 必须可哈希
    except TypeError:
        raise BadRequest("Field 'value' must be a hashable JSON value")

    core.engine().add_fact(Fact(name, value))
    return {"facts": [_fact_to_dict(f) for f in core.engine().get_facts()]}


@api_v1_bp.route("/engine/facts/<string:name>", methods=["GET"])
@auto_handle_exception
def get_fact(name):
    for f in core.engine().get_facts():
        if f.name == name:
            return {"fact": _fact_to_dict(f)}
    raise NotFound(f"Fact not found: {name}")


@api_v1_bp.route("/engine/facts/<string:name>", methods=["DELETE"])
@auto_handle_exception
def delete_fact(name):
    if not core.engine().remove_fact(name):
        raise NotFound(f"Fact not found: {name}")
    return {"facts": [_fact_to_dict(f) for f in core.engine().get_facts()]}


@api_v1_bp.route("/engine/facts", methods=["DELETE"])
@auto_handle_exception
def clear_facts():
    core.engine().clear_facts()
    return {"facts": []}
