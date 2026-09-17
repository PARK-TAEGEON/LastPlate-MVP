"""Run the byte-preserved original suite in a separate temporary checkout."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lastplate-original-') as temp:
        base=Path(temp).resolve()
        with zipfile.ZipFile(root/'preservation/LastPlate-ML-original.zip') as z:
            for entry in z.infolist():
                target=(base/entry.filename).resolve()
                if not target.is_relative_to(base):raise ValueError('Unsafe ZIP member')
                if entry.is_dir():continue
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(z.read(entry))
        completed=subprocess.run([sys.executable,'-m','pytest','-q','-p','no:cacheprovider'],cwd=base/'lastplate-ml',capture_output=True,text=True,encoding='utf-8')
        a.output.write_text(completed.stdout+completed.stderr,encoding='utf-8')
        print(completed.stdout)
        raise SystemExit(completed.returncode)

if __name__=='__main__':main()
