# ./core/__init__.py
from . import engine, model
from core.model import WorkingMemory
from .engine import InferenceEngine

_engine : InferenceEngine = engine.InferenceEngine()

def engine():
    return _engine
