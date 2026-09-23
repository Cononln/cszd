"""Run implemented D-problem subprojects in dependency order."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGES = [
    ("q1", ROOT / "projects" / "q1_capacity_batching"),
    ("q2", ROOT / "projects" / "q2_transport_scheduling"),
    ("q3", ROOT / "projects" / "q3_joint_relay"),
    ("q4", ROOT / "projects" / "q4_partitioning"),
]


def selected_stages(start: str, end: str) -> list[tuple[str, Path]]:
    names = [name for name, _ in STAGES]
    start_index = names.index(start)
    end_index = names.index(end)
    if start_index > end_index:
        raise ValueError("--from 必须位于 --to 之前")
    return STAGES[start_index : end_index + 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="列出各阶段及实现状态")
    parser.add_argument("--from", dest="start", choices=[s[0] for s in STAGES], default="q1")
    parser.add_argument("--to", dest="end", choices=[s[0] for s in STAGES], default="q4")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="遇到尚未实现的阶段时失败；默认跳过并继续",
    )
    args = parser.parse_args()

    stages = selected_stages(args.start, args.end)
    if args.list:
        for name, directory in stages:
            status = "ready" if (directory / "run.py").is_file() else "pending"
            print(f"{name}: {status} ({directory.relative_to(ROOT)})")
        return 0

    for name, directory in stages:
        entrypoint = directory / "run.py"
        if not entrypoint.is_file():
            message = f"{name}: 未找到 {entrypoint.relative_to(ROOT)}"
            if args.strict:
                print(message, file=sys.stderr)
                return 2
            print(f"SKIP {message}")
            continue

        print(f"RUN  {name}: {entrypoint.relative_to(ROOT)}")
        completed = subprocess.run([sys.executable, str(entrypoint)], cwd=ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

