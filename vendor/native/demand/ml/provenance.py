import hashlib
import importlib.metadata
import math
from pathlib import Path

def frame_hash(d):
    return hashlib.sha256(d.to_csv(index=False, date_format='%Y-%m-%d').encode('utf-8')).hexdigest()

def code_version():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for folder in ('ml','tools','adapters'):
        for path in sorted((root/folder).glob('*.py')):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return 'sha256:'+digest.hexdigest()

def dependencies():
    return {p:importlib.metadata.version(p) for p in ('pandas','numpy','scikit-learn','lightgbm','xgboost','joblib','filelock')}

def training_provenance(d, rules_version):
    return dict(feature_rules_version=rules_version,code_version=code_version(),
                data_hash=frame_hash(d), dependencies=dependencies(),
                menu_scope='whole_menu_keyword_presence; main_dish_not_inferred')

def model_parameters(model):
    """Audit JSON retains nonfinite library sentinels as explicit strings."""
    def convert(value):
        if isinstance(value,float) and not math.isfinite(value):
            return 'NaN' if math.isnan(value) else ('Infinity' if value>0 else '-Infinity')
        if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [convert(v) for v in value]
        return value
    return convert(model.get_params())
