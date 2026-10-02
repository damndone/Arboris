"""Post-estimation on the inference kernel: programmed against interfaces.

Every operation reads a persisted inference kernel and nothing else -- no data,
no refit. Whether an operation applies is decided by what the kernel declares
(its interfaces, reference distribution, covariance estimator, weights and
sample), never by the model family's name.
"""

from .core import (
    PostestimationRefusal,
    lincom,
    lr_test,
    nlcom,
    wald_test,
)

__all__ = ["PostestimationRefusal", "lincom", "lr_test", "nlcom", "wald_test"]
