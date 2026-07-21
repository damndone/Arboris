

def test_report_mode_gets_a_longer_ceiling_than_the_provider_default() -> None:
    """A 214-fact report returned 502 at the 60s default while still working.

    Report mode is structurally the largest call this endpoint makes -- every
    fact and figure in one prompt, plus a second corrective round trip when the
    response violates its contract. Raising the shared default instead would
    make every small Ask AI call hang far longer against a dead provider.
    """

    from workbench.http.llm_routes import (
        REPORT_MODE,
        REPORT_MODE_TIMEOUT_S,
        SUPPORTED_MODE,
        _timeout_for_mode,
    )
    from workbench.llm.config import LLMConfig

    config = LLMConfig(base_url="b", api_key="k", model="m", timeout_s=60.0)

    assert _timeout_for_mode(SUPPORTED_MODE, config).timeout_s == 60.0
    assert _timeout_for_mode(REPORT_MODE, config).timeout_s == REPORT_MODE_TIMEOUT_S

    # An operator who already configured a longer timeout keeps it.
    generous = LLMConfig(base_url="b", api_key="k", model="m", timeout_s=400.0)
    assert _timeout_for_mode(REPORT_MODE, generous).timeout_s == 400.0
    # And nothing else about the provider is disturbed.
    assert _timeout_for_mode(REPORT_MODE, config).model == "m"
