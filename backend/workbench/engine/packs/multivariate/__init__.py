"""Standalone multivariate statistical kernels.

The package is intentionally not registered with the Workbench model or Agent
registries in this first slice.  Its public functions are pure-ish adapters
over explicit data frames and option policies, ready for a later capability
adapter without changing the numerical kernels.
"""

from .common import MultivariatePackError, PreparedNumericFrame, prepare_numeric_frame
from .efa import fit_efa
from .pca import fit_pca
from .reliability import cronbach_alpha

__all__ = [
    "MultivariatePackError",
    "PreparedNumericFrame",
    "prepare_numeric_frame",
    "fit_pca",
    "fit_efa",
    "cronbach_alpha",
]
