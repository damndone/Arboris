import pytest

from workbench.engine.pack import AnalysisPack, PackContractError, register_pack


def test_unwired_field_raises_with_planned_version():
    pack = AnalysisPack(pack_id="t_diag", diagnostics=["anything"])
    with pytest.raises(PackContractError) as exc:
        register_pack(pack)
    msg = str(exc.value)
    assert "diagnostics" in msg
    assert "V1.5.6" in msg  # the annotated planned version


@pytest.mark.parametrize("field", [
    "diagnostics", "report_blocks", "recommended_actions", "interpretation_restrictions",
])
def test_each_alarmed_field_raises(field):
    pack = AnalysisPack(pack_id=f"t_{field}", **{field: ["x"]})
    with pytest.raises(PackContractError):
        register_pack(pack)


def test_wired_fields_do_not_raise():
    # empty pack — wired fields default empty — must register cleanly
    register_pack(AnalysisPack(pack_id="t_empty"))
