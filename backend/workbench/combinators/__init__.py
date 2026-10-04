"""Combinators: run one capability several times and combine the results.

Multiple imputation is the first (v1.8.10 design section 3.5); by-group
execution follows. A combinator works on inference kernels, never on a family
name, and offers a family only where its combination has been checked against a
reference implementation.
"""

from .multiple_imputation import (
    MI_VALIDATED,
    MultipleImputationRefusal,
    pool_kernels,
    require_poolable,
)

__all__ = ["MI_VALIDATED", "MultipleImputationRefusal", "pool_kernels", "require_poolable"]
