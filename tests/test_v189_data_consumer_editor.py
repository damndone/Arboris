from __future__ import annotations


def test_data_consumer_extensions_publish_closed_editor_schemas_and_unavailable_native_formats() -> None:
    from workbench.data_operation_manifest import build_data_operation_manifest

    manifest = build_data_operation_manifest().to_dict()
    descriptors = {item["operation_id"]: item for item in manifest["operations"]}

    metadata = descriptors["data.metadata.update"]["request_schema"]
    assert metadata["additionalProperties"] is False
    assert {
        "metadata",
        "weight",
        "split",
        "group",
    } <= set(metadata["properties"])
    assert metadata["properties"]["metadata"]["type"] == "object"

    for operation_id in ("data.sort", "data.split", "data.recode"):
        schema = descriptors[operation_id]["request_schema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["operation"]["enum"] == [
            operation_id.removeprefix("data.")
        ]
        assert schema["properties"]["parameters"]["additionalProperties"] is False

    unavailable = {item["operation_id"]: item for item in manifest["unavailable"]}
    assert {
        "data.interchange.sav",
        "data.interchange.zsav",
        "data.interchange.dta",
    } <= set(unavailable)
    assert all(item["status"] == "unavailable" for item in unavailable.values())
