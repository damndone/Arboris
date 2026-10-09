"""Estimation columns and explicit product terms from a verified formula.

A public coefficient name is not a formula: ``x:z`` may be a single source
column. Only a family's reconstructed DesignInfo may declare it a product.
"""
from types import MappingProxyType

import numpy as np

from ..formula_terms import interaction_factors, public_term
from .core import PostestimationRefusal


class DesignColumns(dict):
    def __init__(self, columns, *, products=None, continuous_variables=None):
        super().__init__(columns)
        self.product_factors = MappingProxyType(dict(products or {}))
        self.continuous_variables = (None if continuous_variables is None
                                     else frozenset(continuous_variables))


def design_from_patsy(matrix, design_info, *, continuous_variables=None):
    """Project the genuine formula terms before public column-name decoding."""
    raw_names = list(design_info.column_names)
    names = [public_term(name) for name in raw_names]
    values = np.asarray(matrix, dtype=float)
    if len(set(names)) != len(names) or values.ndim != 2 or values.shape[1] != len(names):
        raise PostestimationRefusal("DESIGN_MISMATCH", "Formula columns are ambiguous or do not match the estimation matrix")
    products = {}
    for term in design_info.terms:
        if len(term.factors) < 2:
            continue
        # The term's factor count establishes that this IS an interaction.
        # Split its still-quoted expanded column names only to identify each
        # encoded factor column (e.g. a treatment dummy and a numeric input).
        selection = design_info.term_name_slices[term.name()]
        for raw_name in raw_names[selection]:
            factors = interaction_factors(raw_name)
            if len(factors) != len(term.factors):
                raise PostestimationRefusal("TRANSFORMED_TERM", "The formula interaction cannot be resolved to its factor columns")
            products[public_term(raw_name)] = tuple(public_term(factor) for factor in factors)
    return DesignColumns(zip(names, values.T), products=products, continuous_variables=continuous_variables)
