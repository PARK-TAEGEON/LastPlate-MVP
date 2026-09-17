"""Immutable releases and one atomic current pointer. Local trusted artifacts only."""
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
import joblib
from filelock import FileLock
from .config import SCHEMA_VERSION
from .provenance import code_version,dependencies

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

class ModelRegistry:
    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)

    def current_version(self):
        p = self.path / 'current.json'
        return json.loads(p.read_text(encoding='utf-8'))['model_version'] if p.exists() else None

    def load(self, version=None):
        version = version or self.current_version()
        if not version or Path(version).name != version or '/' in version or '\\' in version:
            raise ValueError('No valid model version')
        folder = self.path / 'releases' / version
        metadata = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
        model_path = folder / 'demand_model.pkl'
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != metadata['model_sha256']:
            raise ValueError('Model artifact checksum mismatch')
        if metadata['schema_version'] != SCHEMA_VERSION:
            raise ValueError('Unsupported feature schema version')
        bundle = joblib.load(model_path)
        if bundle['features'] != metadata['features']:
            raise ValueError('Model/metadata feature mismatch')
        return bundle, metadata

    def promote(self, bundle, metadata, expected_current=None):
        saved=self.prepare_release(bundle,metadata)
        return self.activate(saved['model_version'],expected_current)

    def prepare_release(self,bundle,metadata,version=None):
        version=version or 'v'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        if Path(version).name!=version or '/' in version or '\\' in version:
            raise ValueError('Invalid model version')
        folder=self.path/'releases'/version
        if folder.exists():
            raise ValueError('Immutable release already exists')
        stage=self.path/'staging'/version
        stage.mkdir(parents=True,exist_ok=False)
        joblib.dump(bundle,stage/'demand_model.pkl')
        with (stage/'demand_model.pkl').open('r+b') as f:
            os.fsync(f.fileno())
        provenance=dict(feature_rules_version=bundle.get('feature_rules_version','v1'),
                        code_version=code_version(),data_hash=None,dependencies=dependencies())
        provenance.update(bundle.get('provenance',{}))
        meta=dict(provenance)
        meta.update(metadata)
        meta.update(model_version=version,schema_version=SCHEMA_VERSION,trained_at=datetime.now(timezone.utc).isoformat(),
                    features=bundle['features'],feature_group=bundle['group'],
                    model_sha256=hashlib.sha256((stage/'demand_model.pkl').read_bytes()).hexdigest())
        atomic_json(stage/'metadata.json',meta)
        folder.parent.mkdir(parents=True,exist_ok=True)
        os.replace(stage,folder)
        return meta

    def activate(self,version,expected_current=None):
        with FileLock(str(self.path / '.registry.lock')):
            current = self.current_version()
            _,meta=self.load(version)
            if current==version:
                return meta
            if current != expected_current:
                raise RuntimeError('Incumbent changed during training; reevaluate before promotion')
            if current:
                archive = self.path / 'archive' / current
                if not archive.exists():
                    stage=archive.with_name(current+'.'+uuid.uuid4().hex+'.tmp')
                    shutil.copytree(self.path / 'releases' / current,stage)
                    os.replace(stage,archive)
            atomic_json(self.path / 'current.json', {'model_version': version})
            return meta
