import hashlib
import importlib.metadata
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
