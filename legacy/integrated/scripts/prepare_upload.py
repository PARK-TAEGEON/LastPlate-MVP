"""Copy only this integration's sources into a fresh team-repository clone.

No git commands, overwrites, deletes, commits or uploads are performed.
Usage: python scripts/prepare_upload.py C:/path/to/fresh-clone
"""
import argparse
from pathlib import Path
import shutil

SOURCE = Path(__file__).resolve().parents[1]
DIRECTORIES = ['backend/app', 'backend/tests', 'backend/ml_bundle', 'frontend']
FILES = ['backend/requirements.txt', 'backend/.gitignore', 'docs/api-contract.md',
         'docs/operation-integration.md', 'docs/GITHUB-UPLOAD.md',
         'docs/examples/operation-plan-request.json', 'scripts/import_ml_bundle.py',
         'scripts/package_release.py', 'scripts/prepare_upload.py']


def sources():
    result = [(SOURCE / file, Path(file)) for file in FILES]
    for directory in DIRECTORIES:
        for source in sorted((SOURCE / directory).rglob('*')):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix not in ('.pyc','.pyo'):
                if source.is_symlink():
                    raise ValueError(f'Symlink not allowed: {source}')
                result.append((source, source.relative_to(SOURCE)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve(strict=True)
    if destination == SOURCE or not (destination / '.git').exists():
        parser.error('Destination must be a different, already cloned git repository.')
    files = sources()
    for source, relative in files:
        target = destination / relative
        if not target.resolve().is_relative_to(destination):
            parser.error(f'Target outside clone: {relative}')
        if target.exists() or target.is_symlink():
            parser.error(f'Refusing to overwrite existing file: {relative}. Ask your team to merge it.')
        if not source.is_file():
            parser.error(f'Missing source file: {source}')
    for source, relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f'Copied {len(files)} source files to {destination}')
    print('Existing root README/app.py/requirements.txt/.gitignore unchanged. No commit or push performed.')


if __name__ == '__main__':
    main()
