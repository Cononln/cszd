"""Small standalone Q3-A communication validation wrapper."""
from __future__ import annotations

try:
    from .audit_q3_a import _unit_tests
    from .data_q3 import load_q3_inputs
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from q3.audit_q3_a import _unit_tests
    from q3.data_q3 import load_q3_inputs


def validate() -> dict:
    rows = _unit_tests(load_q3_inputs())
    return {"status": "PASS" if all(bool(row["pass"]) for row in rows) else "FAIL",
            "tests": rows}


if __name__ == "__main__":
    import json
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
