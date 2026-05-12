"""diagnostic_preview package.

V1.3.2 split this from a single file into focused submodules. The public
surface is unchanged: callers continue to import
`build_diagnostic_summary_preview` from `workbench.diagnostic_preview`.
"""
from ._entry import build_diagnostic_summary_preview

__all__ = ["build_diagnostic_summary_preview"]
