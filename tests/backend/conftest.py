import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from recognition import netguard  # noqa: E402

# Every backend test runs with outbound networking refused, like the app.
netguard.install()


def pytest_configure(config):
    if not config.option.basetemp:  # the system temp folder may not be writable in sandboxes
        config.option.basetemp = str(ROOT / 'test-output' / 'pytest-tmp')
    config.addinivalue_line('markers', 'real_model: runs the actual pix2tex model (slow, needs setup)')
