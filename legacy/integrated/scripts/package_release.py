"""Generate a source-only ZIP. Never include environment, DB, credentials or raw training data."""
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from prepare_upload import SOURCE, sources


def main():
    output = SOURCE / 'output'
    output.mkdir(exist_ok=True)
    filename = output / f'LastPlate-integrated-{datetime.now():%Y%m%d-%H%M%S}.zip'
    files = sources() + [(SOURCE/'README.md', Path('README.md')), (SOURCE/'.gitignore', Path('.gitignore'))]
    with ZipFile(filename, 'x', compression=ZIP_DEFLATED) as archive:
        for source, relative in files:
            archive.write(source, str(Path('LastPlate-integrated')/relative))
    print(filename)
    print(f'{len(files)} files, {filename.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
