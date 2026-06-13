from workbench.engine.capabilities import MODEL_UI_META, MODEL_UI_ORDER


def test_did_in_capabilities_meta():
    assert "did" in MODEL_UI_META
    entry = MODEL_UI_META["did"]
    assert entry["group"] == "DID"
    assert "label" in entry and "description" in entry


def test_did_in_capabilities_order():
    assert "did" in MODEL_UI_ORDER
