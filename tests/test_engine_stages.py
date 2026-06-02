from workbench.engine.stages import Stage, PIPELINE


def test_pipeline_is_ordered_list_of_unique_named_stages():
    assert isinstance(PIPELINE, list)
    names = [s.name for s in PIPELINE]
    assert len(names) == len(set(names))


def test_stage_protocol_shape():
    class Noop:
        name = "noop"

        def run(self, ctx, env):
            return ctx

    s: Stage = Noop()
    assert s.name == "noop"
