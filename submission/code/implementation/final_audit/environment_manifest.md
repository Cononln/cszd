# Environment manifest

{
  "status": "PASS",
  "python": "3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]",
  "platform": "Windows-11-10.0.26100-SP0",
  "requirements": {
    "implementation/q1/requirements.txt": [
      "matplotlib",
      "numpy",
      "openpyxl",
      "ortools",
      "pandas",
      "rasterio",
      "seaborn",
      ""
    ],
    "implementation/q2/requirements.txt": [
      "# Q2 与 Q1 共用的运行依赖",
      "matplotlib",
      "numpy",
      "openpyxl",
      "ortools",
      "pandas",
      "rasterio",
      "seaborn",
      "",
      "# Q2-D 使用；Q2-A 不调用优化器",
      "alns>=1.1"
    ],
    "implementation/q3/requirements.txt": [
      "# Q3 uses the shared physical and communication dependencies plus a joint MILP solver.",
      "-r ../q1/requirements.txt",
      "scipy"
    ]
  },
  "solver_notes": [
    "Q1 deterministic staged solver",
    "Q2 CP-SAT/ALNS with recorded seeds",
    "Q3 bounded C2 repair and relay decoder",
    "Q4 deterministic exhaustive enumeration"
  ]
}
