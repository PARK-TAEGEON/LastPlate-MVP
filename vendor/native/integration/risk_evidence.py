"""Load the native pure projector without importing legacy tools/config packages."""
import importlib.util
from .contracts import ROOT
spec=importlib.util.spec_from_file_location('_lastplate_native_active_evidence',ROOT/'inventory_risk/tools/active_evidence.py')
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
project_active=native.project_active
