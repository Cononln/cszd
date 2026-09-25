# Reproduce

Run from the repository root with Python 3.11+. The compact executable mirror is under `submission/code/`.

1. `python implementation/final_audit/audit_project_final.py --audit-only`.
2. Q1: `python implementation/q1/code/q1/audit_physics.py`.
3. Q2: `python implementation/q2/code/q2/run_q2.py --mode formal`.
4. Q3: set `PYTHONPATH=implementation/q3/code` and run `python -m q3.run_q3_final --mode reproduce`.
5. Q4: set `PYTHONPATH=implementation/q4/code` and run `python -m q4.run_q4_final --mode reproduce`, then `python -m q4.compare_q4_reproduction`.

The default review path is the audit-only manifest check; full optimization reruns are optional.
