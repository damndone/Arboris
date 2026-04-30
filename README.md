# Local Econometrics Workbench

Set up the local Python package:

```bash
python3 -m pip install -e ".[dev]"
```

Run the backend tests:

```bash
pytest
```

Create a project and run a sample dataset:

```bash
workbench create /tmp workbench-demo
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv --y wage --x education
```

Start the local API:

```bash
uvicorn workbench.api:app --reload
```

Start the local UI:

```bash
cd frontend
npm install
npm run dev
```

The V1 workflow writes outputs into `project/runs/{run_id}/`, including `run_manifest.json`, `environment.json`, `decisions.json`, `errors.json`, `artifacts_index.json`, reports, figures, tables, and processed data.
