from __future__ import annotations

from io import BytesIO

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.input import audit_time_value_input
from workbench.engine.packs.arma_garch.transforms import build_transform_profiles


def test_transform_preflight_uses_the_full_confirmed_missing_policy_analysis_view(
    tmp_path,
) -> None:
    client = TestClient(app)
    project = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "preflight"}
    ).json()["project_root"]
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-02", periods=30),
            "vix": [
                *(12.0 + np.arange(15, dtype=float)),
                np.nan,
                *(30.0 + np.arange(14, dtype=float)),
            ],
        }
    )
    raw = frame.to_csv(index=False).encode("utf-8")
    contract = ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "preflight:upload:vix.csv",
            "time_column": "date",
            "value_column": "vix",
            "time_index_semantics": "business_or_trading_observations",
            "transform": "level",
            "transform_confirmed": True,
            "missing_value_policy": "drop_missing_confirmed",
            "validation": {},
        }
    )
    audited = audit_time_value_input(frame, contract)
    profiles = build_transform_profiles(audited.analysis_view)
    recommended = max(
        (profile for profile in profiles.values() if profile.eligible),
        key=lambda profile: profile.recommendation_score,
    )

    response = client.post(
        "/runs/arma-garch/transform-preflight",
        data={
            "project_root": project,
            "time_column": "date",
            "value_column": "vix",
            "time_index_semantics": "business_or_trading_observations",
            "missing_value_policy": "drop_missing_confirmed",
        },
        files={"file": ("vix.csv", BytesIO(raw), "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "source_row_count": len(frame),
        "analysis_row_count": len(audited.analysis_view),
        "diagnostics": [item.to_dict() for item in audited.diagnostics],
        "transform_profiles": {
            transform_id: profile.to_dict()
            for transform_id, profile in profiles.items()
        },
        "recommendation": {
            "transform_id": recommended.transform_id,
            "score": recommended.recommendation_score,
            "reason": recommended.recommendation_reason,
        },
        "transform_confirmation_required": True,
    }
    assert response.json()["analysis_row_count"] == 29
    assert response.json()["transform_profiles"]["level"]["n_effective"] == 29


def test_transform_preflight_block_policy_returns_the_missing_value_diagnostic(
    tmp_path,
) -> None:
    client = TestClient(app)
    project = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "preflight-block"}
    ).json()["project_root"]
    raw = pd.DataFrame(
        {
            "date": pd.bdate_range("2025-01-02", periods=4),
            "vix": [12.0, np.nan, 14.0, 15.0],
        }
    ).to_csv(index=False).encode("utf-8")

    response = client.post(
        "/runs/arma-garch/transform-preflight",
        data={
            "project_root": project,
            "time_column": "date",
            "value_column": "vix",
            "time_index_semantics": "business_or_trading_observations",
            "missing_value_policy": "block",
        },
        files={"file": ("vix.csv", BytesIO(raw), "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALUE_PARSE_FAILED"
    assert response.json()["detail"]["message"] == "value column contains missing entries"
