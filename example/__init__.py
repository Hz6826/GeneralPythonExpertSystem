# ./example/__init__.py
from . import network

REGISTRIES = {
    network.__name__: network,
}

def get_list():
    return list(REGISTRIES.keys())

def has(name):
    return name in REGISTRIES

def get(name):
    return REGISTRIES[name]
