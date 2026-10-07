"""Export adapters for persisted source normalization and feature recipes."""
from __future__ import annotations

import math
from workbench.predictive_research.contracts import FeatureRecipeV1
from workbench.contracts.common.envelope import thaw_json
from .exporters import native, snapshot
from .exporters.data import setup, column
from .syntax import identifier, literal, refuse
from . import absorbing_panel


def cleaning_capability(step):
    if step.parameters.get('identity') is not True:
        return 'Executed cleaning and type normalization are continued from a verified local dataset snapshot.'


def cleaning(step, ctx):
    return setup(step, ctx)[2]


def feature_capability(step):
    parameters = thaw_json(step.parameters)
    numeric = parameters.pop('native_inputs_numeric', True)
    recipe = FeatureRecipeV1(**parameters)
    recipe.validate()
    if numeric is not True:
        return 'Recorded numeric-text coercion continues from its verified Workbench feature snapshot; native coercion rules are not equivalent.'
    if recipe.operation_id not in {'derived_variable', 'interaction', 'log', 'ratio'}:
        return 'This recorded feature transformation continues from its verified local dataset snapshot.'


def feature(step, ctx):
    p, target, lines = setup(step, ctx)
    p.pop('native_inputs_numeric', None)
    recipe = FeatureRecipeV1(**p); recipe.validate()
    options = dict(recipe.parameters); language = ctx.language
    output = column(target, recipe.outputs[0], language)
    def numeric(name):
        value = column(target, name, language)
        # Arithmetic recipes coerce text numerics in Workbench. Fail closed for
        # nonnumeric native data instead of introducing different coercion rules.
        lines.append(f'assert pd.api.types.is_numeric_dtype({value})' if language == 'python' else
            (f'stopifnot(is.numeric({value}))' if language == 'r' else f'confirm numeric variable {identifier(name)}'))
        return value
    if recipe.operation_id == 'derived_variable':
        left, right = map(numeric, recipe.inputs)
        expression = f'({left} {dict(add="+", subtract="-", multiply="*")[options["operator"]]} {right})'
    elif recipe.operation_id == 'interaction':
        expression = f'({numeric(options["left"])} * {numeric(options["right"])})'
    elif recipe.operation_id == 'ratio':
        numerator, denominator = numeric(options['numerator']), numeric(options['denominator'])
        lines.append(f'assert ({denominator}.notna() & ({denominator} != 0)).all()' if language == 'python' else
            (f'stopifnot(all(!is.na({denominator}) & {denominator} != 0))' if language == 'r' else f'assert !missing({denominator}) & {denominator} != 0'))
        expression = f'({numerator} / {denominator})'
    else:
        value = numeric(options['input'])
        lines.append(f'assert ({value}.notna() & ({value} > 0)).all()' if language == 'python' else
            (f'stopifnot(all(!is.na({value}) & {value} > 0))' if language == 'r' else f'assert !missing({value}) & {value} > 0'))
        expression = f'{"np.log" if language == "python" else "log"}({value})'
        if options.get('base', 'e') != 'e':
            base = float(options['base'])
            if not math.isfinite(base) or base <= 0 or base == 1:
                refuse('Invalid logarithm base')
            expression += ' / ' + literal(math.log(base), language)
    lines.append(f'{output} = {expression}' if language == 'python' else
        (f'{output} <- {expression}' if language == 'r' else f'generate double {output} = {expression}'))
    return lines


EXPORTERS = {spec.operation: spec for spec in (
    native('data.cleaning', cleaning, cleaning_capability),
    native('data.estimation_input', absorbing_panel.prepare, absorbing_panel.capability),
    snapshot('model.time_series.ets', 'Completed exponential-smoothing parameters and diagnostics continue from verified result documents; native optimization equivalence is not validated.'),
    snapshot('model.time_series.arma_garch', 'Completed joint likelihood, parameters, diagnostics and forecast roles continue from verified result documents; native re-estimation is not validated.'),
    native('data.feature_recipe', feature, feature_capability),
    snapshot('data.column.cast', 'Recorded strict column conversion continues from its verified Workbench dataset snapshot.'),
    snapshot('data.columns.cast', 'Recorded strict batch conversion continues from its verified Workbench dataset snapshot.'),
)}
