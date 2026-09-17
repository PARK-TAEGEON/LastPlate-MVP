"""Reuse the native pure helper without importing colliding legacy packages."""
import importlib.util
from .contracts import ROOT

spec = importlib.util.spec_from_file_location(
    '_lastplate_native_usable_stock', ROOT / 'inventory_risk/tools/usable_stock.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
usable_stock = native.usable_stock
