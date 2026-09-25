"""Q3-A audit entry point; no final joint optimisation is run."""
from __future__ import annotations

import json

try:
    from .audit_q3_a import run_audit
except ImportError:  # direct ``python path/to/run_q3.py`` invocation
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from q3.audit_q3_a import run_audit


if __name__ == "__main__":
    print(json.dumps(run_audit(), ensure_ascii=False, indent=2))
