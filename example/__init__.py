# ./example/__init__.py
import inspect

from . import aircon, automotive, crop, ml_training, network

REGISTRIES = {
    network.__name__: network,
    automotive.__name__: automotive,
    aircon.__name__: aircon,
    crop.__name__: crop,
    ml_training.__name__: ml_training,
}

def get_list():
    return list(REGISTRIES.keys())

def has(name):
    return name in REGISTRIES

def get(name):
    return REGISTRIES[name]

def get_doc(name):
    """返回该示例模块的 docstring（markdown），没有就返回空串。"""
    return inspect.getdoc(REGISTRIES[name]) or ""
