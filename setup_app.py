"""One-time setup for Say the Math. Network access happens only here, and only to the pinned sources.

  python setup_app.py            create .venv, install pinned Python and Node packages, download and
                                 verify the pix2tex checkpoints, load the model once and record results
  python setup_app.py --check    verify an existing setup without using the network

What is downloaded:
  - Python packages from PyPI; torch/torchvision CPU wheels from download.pytorch.org (Windows/Linux)
  - Node packages from the npm registry, exactly as listed in package-lock.json (npm ci)
  - weights.pth and image_resizer.pth from the pix2tex v0.0.1 GitHub release, checked against SHA256
After setup the app needs no network. It refuses outbound connections at runtime.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / '.venv'
MODELS = ROOT / 'models'
SUPPORTED_PY = ((3, 11), (3, 12))  # torch 2.5.1 wheels end at 3.12; pinned pandas/scipy need 3.11+
TORCH_CPU_INDEX = 'https://download.pytorch.org/whl/cpu'
MAX_ROOT_CHARS = 80  # without Windows long-path support

sys.path.insert(0, str(ROOT))
from recognition import config  # noqa: E402  (stdlib-only module)


def say(msg):
    print(f'[setup] {msg}', flush=True)


def fail(msg, code=1):
    print(f'[setup] ERROR: {msg}', file=sys.stderr, flush=True)
    sys.exit(code)


def venv_python() -> Path:
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def run(cmd, **kw):
    say('$ ' + ' '.join(f'"{c}"' if ' ' in str(c) else str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        fail(f'command failed with exit code {r.returncode}')
    return r


def check_python():
    v = sys.version_info[:2]
    if not (SUPPORTED_PY[0] <= v <= SUPPORTED_PY[1]):
        fail(f'Python {v[0]}.{v[1]} is not supported. Install Python 3.12 or 3.11 (64-bit) and run setup with it.')
    if sys.maxsize <= 2 ** 32:
        fail('64-bit Python is required.')


def check_path_length():
    """pip writes paths up to ~175 characters below the project folder (transformers, setuptools)."""
    if os.name != 'nt':
        return
    enabled = 0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as k:
            enabled = winreg.QueryValueEx(k, 'LongPathsEnabled')[0]
    except OSError:
        pass
    if not enabled and len(str(ROOT)) > MAX_ROOT_CHARS:
        fail(f'The project folder path is {len(str(ROOT))} characters long. Windows limits file paths to 260 '
             f'characters and the installed packages need about 175 below this folder. Move the folder to a '
             f'shorter path (at most {MAX_ROOT_CHARS} characters, for example C:\\SayTheMath) and run setup again.')


def make_venv():
    py = venv_python()
    if py.exists():
        r = subprocess.run([str(py), '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'], capture_output=True, text=True)
        ver = tuple(int(x) for x in r.stdout.strip().split('.')) if r.returncode == 0 else None
        if ver and SUPPORTED_PY[0] <= ver <= SUPPORTED_PY[1]:
            say(f'using existing environment .venv (Python {ver[0]}.{ver[1]})')
            return py
        fail('.venv exists but uses an unsupported or broken Python. Delete the .venv folder and run setup again.')
    say('creating isolated environment .venv')
    run([sys.executable, '-m', 'venv', str(VENV)])
    return py


def install_python_packages(py):
    torch_req = ROOT / ('requirements-torch-macos.txt' if sys.platform == 'darwin' else 'requirements-torch-cpu.txt')
    cmd = [py, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', torch_req, '-c', ROOT / 'requirements-lock.txt']
    if sys.platform != 'darwin':
        cmd += ['--index-url', TORCH_CPU_INDEX]
    run(cmd)
    run([py, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', ROOT / 'requirements.txt',
         '-c', ROOT / 'requirements-lock.txt'])
    if os.environ.get('SAYTHEMATH_DEV') == '1':
        run([py, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', ROOT / 'requirements-dev.txt'])


def install_node_packages():
    node = shutil.which('node')
    npm = shutil.which('npm')
    if not node or not npm:
        fail('Node.js 18 or newer is required (https://nodejs.org). Install it, then run setup again.')
    r = subprocess.run([node, '--version'], capture_output=True, text=True)
    major = int(r.stdout.strip().lstrip('v').split('.')[0]) if r.returncode == 0 else 0
    if major < 18:
        fail(f'Node.js {r.stdout.strip()} is too old; version 18 or newer is required.')
    run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--omit=dev'], cwd=str(ROOT))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download_checkpoints():
    MODELS.mkdir(exist_ok=True)
    for name, spec in config.CHECKPOINTS.items():
        dest = MODELS / name
        if dest.exists() and sha256(dest) == spec['sha256']:
            say(f'{name}: present, SHA256 verified')
            continue
        part = dest.with_suffix(dest.suffix + '.part')
        for attempt in range(1, 4):
            say(f'downloading {name} from {spec["url"]} (attempt {attempt})')
            try:
                req = urllib.request.Request(spec['url'], headers={'User-Agent': 'say-the-math-setup'})
                with urllib.request.urlopen(req, timeout=60) as resp, open(part, 'wb') as out:
                    total = int(resp.headers.get('Content-Length') or 0)
                    done = 0
                    last = 0.0
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if total and time.time() - last > 2:
                            say(f'  {done / 1e6:.1f} / {total / 1e6:.1f} MB')
                            last = time.time()
            except Exception as e:  # network errors: retry
                say(f'  download failed: {e}')
                time.sleep(2 * attempt)
                continue
            got = sha256(part)
            if got != spec['sha256']:
                part.unlink(missing_ok=True)
                fail(f'{name} SHA256 mismatch (got {got}). The file was deleted. Do not use it.')
            os.replace(part, dest)
            say(f'{name}: downloaded, SHA256 verified')
            break
        else:
            fail(f'could not download {name}. Check the internet connection and run setup again.')


def selfcheck(py):
    """Load the real model once in the venv, count parameters and record versions (no network)."""
    run([py, '-m', 'recognition.selfcheck', '--write', str(config.SETUP_RECORD)], cwd=str(ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='verify an existing setup without network access')
    ap.add_argument('--skip-python', action='store_true', help='do not (re)install Python packages')
    ap.add_argument('--skip-node', action='store_true', help='do not (re)install Node packages')
    a = ap.parse_args()
    say(f'project folder: {ROOT}')
    if a.check:
        py = venv_python()
        if not py.exists():
            fail('.venv is missing. Run setup without --check first.')
        selfcheck(py)
        say('setup check passed')
        return
    check_python()
    check_path_length()
    py = make_venv()
    if not a.skip_python:
        install_python_packages(py)
    if not a.skip_node:
        install_node_packages()
    download_checkpoints()
    selfcheck(py)
    say('setup complete. Start the app with Start-Windows.cmd (Windows) or ./start.sh (macOS/Linux).')


if __name__ == '__main__':
    main()
