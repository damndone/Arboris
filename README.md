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
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv wage --x education
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

## V1.1 Result Browser

The frontend History tab lets you browse all runs for a project, inspect run detail, and download artifacts without leaving the browser. The backend exposes five read-only endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/runs?project_root=...` | List runs with status, mode, y, x summary |
| GET | `/runs/{run_id}?project_root=...` | Run detail with artifact counts and errors |
| GET | `/runs/{run_id}/artifacts?project_root=...` | Artifact index grouped by type |
| GET | `/runs/{run_id}/artifacts/{artifact_id}?project_root=...` | Download artifact file |
| GET | `/runs/{run_id}/report?project_root=...` | Serve `report.html` for iframe embedding |
