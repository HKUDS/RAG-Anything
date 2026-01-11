### 1. Definition exp in file work-space/src/definitions.py
Example: 
    "exp1_baseline": ExperimentDef(
        id="exp1_baseline",
        description="Default Settings (Chunk 1200, Auto Gleaning)",
        lightrag_kwargs={}
    ),

### 2. Run all exps:
``` bash
python run_bench.py
```

### 3. Run a specific exp:
``` bash
python run_bench.py --exp ${exp_name}
```
Output will be in benchmark_report.csv