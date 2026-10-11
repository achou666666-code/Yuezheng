#!/usr/bin/env python3
"""Test an installed Git snapshot, excluding local source edits and editable installs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Committed revision or staged tree to test')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env['PYTHONNOUSERSITE'] = '1'
    with tempfile.TemporaryDirectory(prefix='yuezheng-install-') as folder:
        work = Path(folder)
        source = work / 'source'
        source.mkdir()
        archive = work / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), args.ref], cwd=repo, check=True)
        subprocess.run(['tar', '-xf', str(archive), '-C', str(source)], check=True)
        subprocess.run([sys.executable, '-m', 'venv', str(work / 'venv')], check=True, env=env)
        python = work / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run([str(python), '-m', 'pip', 'install', str(source) + '[test,image,audio,websocket,mcp]'], check=True, env=env)
        subprocess.run([str(python), '-c',
            'from pathlib import Path; import yuezheng; '
            'p=Path(yuezheng.__file__).resolve(); print("Installed package:",p); '
            'assert "site-packages" in p.parts, "Test is using a source checkout"'], cwd=work, check=True, env=env)
        subprocess.run([str(python), '-m', 'pytest', '-q', '-rs'], cwd=source, check=True, env=env)
    print('Clean installation checks passed for ' + args.ref)


if __name__ == '__main__':
    main()
