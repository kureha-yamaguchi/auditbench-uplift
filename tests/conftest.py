import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "grader" / "fixtures"


@pytest.fixture
def write_json(tmp_path):
    def _write(obj, name="findings.json", raw: bytes | None = None):
        p = tmp_path / name
        p.write_bytes(raw if raw is not None else json.dumps(obj).encode())
        return p
    return _write
