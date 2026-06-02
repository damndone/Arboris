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

## V1.5.3.1 Backend Expansion

V1.5.3.1 adds explicit model types, prediction-only ML artifacts, MICE imputation, and imbalanced sampling - all backend-only. See [docs/v1.5.3.1-release-notes.md](docs/v1.5.3.1-release-notes.md) for details.

### Optional extras

```bash
pip install -e ".[panel]"       # linearmodels for panel_ols
pip install -e ".[ml]"          # scikit-learn for prediction_lasso/ridge/random_forest
pip install -e ".[imbalanced]"  # imbalanced-learn for smote/oversample/undersample
pip install -e ".[imputation]"  # statsmodels (already in base)
```

### Explicit model types

```bash
# Probit on binary outcome
workbench run project/ data.csv outcome --x x1 --x x2 --model-type probit

# Negative binomial on count outcome
workbench run project/ data.csv events --x x1 --x x2 --model-type negative_binomial

# GLM with explicit family
workbench run project/ data.csv events --x x1 --x x2 --model-type glm:poisson
```

The default `auto` mode only routes to OLS / Logit / Poisson. Advanced model types must be requested explicitly.

### Prediction-only mode

Enable in `config.yml`:

```yaml
prediction_enabled: true
prediction_model_type: prediction_lasso
prediction_cv_folds: 5
```

Prediction outputs are isolated under `prediction_results/` and are never treated as causal or econometric inference.

## V1.1 Result Browser

The frontend History tab lets you browse all runs for a project, inspect run detail, and download artifacts without leaving the browser. The backend exposes five read-only endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/runs?project_root=...` | List runs with status, mode, y, x summary |
| GET | `/runs/{run_id}?project_root=...` | Run detail with artifact counts and errors |
| GET | `/runs/{run_id}/artifacts?project_root=...` | Artifact index grouped by type |
| GET | `/runs/{run_id}/artifacts/{artifact_id}?project_root=...` | Download artifact file |
| GET | `/runs/{run_id}/report?project_root=...` | Serve `report.html` for iframe embedding |
