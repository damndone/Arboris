from .templates import TEMPLATES


def render_template(template_key: str, params: dict) -> str:
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown template_key: {template_key}")

    spec = TEMPLATES[template_key]
    missing = set(spec.get("required_params", [])) - set(params)

    if missing:
        raise ValueError(
            f"Missing template params for {template_key}: {sorted(missing)}"
        )

    return spec["text"].format(**params)
