"""Published model schemas must survive a fresh interpreter's hash seed."""
import os
import subprocess
import sys

from workbench.agent.workflow_contracts import workflow_proposal_schema, workflow_step_operations


def test_published_operation_schema_is_identical_across_process_hash_seeds():
    source = (
        "import hashlib,json; from workbench.agent.operations import OperationRegistry; "
        "s=OperationRegistry().proposal_tool_schema(); "
        "print(hashlib.sha256(json.dumps(s,sort_keys=True,separators=(',',':')).encode()).hexdigest())"
    )
    outputs = [subprocess.check_output([sys.executable, "-c", source], text=True,
                env={**os.environ, "PYTHONHASHSEED": seed}).strip() for seed in ("3", "71")]
    assert outputs[0] == outputs[1]


def test_workflow_operation_enum_has_all_live_ids_in_a_stable_order():
    values = workflow_proposal_schema()["properties"]["changes"]["properties"]["steps"]["items"]["properties"]["operation_id"]["enum"]
    assert values == sorted(workflow_step_operations())
