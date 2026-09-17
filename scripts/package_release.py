from pathlib import Path
import zipfile,hashlib,json

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT.parent/'LastPlate-MVP-UX-v1.1.0.zip'
EXCLUDED={'.venv','venv','__pycache__','.pytest_cache','.git','node_modules'}
with zipfile.ZipFile(DEST,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(ROOT.rglob('*')):
        relative=p.relative_to(ROOT)
        if (not p.is_file() or set(relative.parts)&EXCLUDED or relative.parts[0] in ('work','data')
            or relative.parts[:3]==('vendor','native','runtime') or p.suffix in ('.pyc','.db')
            or p.name.endswith(('.db-wal','.db-shm','.lock'))):
            continue
        z.write(p,Path('lastplate-mvp')/relative)
with zipfile.ZipFile(DEST) as z:
    assert z.testzip() is None
    for entry in json.loads((ROOT/'reports/native-preservation.json').read_text(encoding='utf-8')):
        content=z.read('lastplate-mvp/vendor/native/'+entry['path'])
        assert hashlib.sha256(content).hexdigest()==entry['sha256'],entry['path']
    count=len(z.namelist())
print(json.dumps({'file':str(DEST),'files':count,'bytes':DEST.stat().st_size,
                  'sha256':hashlib.sha256(DEST.read_bytes()).hexdigest()},indent=2))
