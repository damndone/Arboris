"""Declarative bootstrap seam for future model packs."""

from .loader import PackDeclaration, bootstrap_builtin_packs, load_declared_packs

__all__ = ["PackDeclaration", "bootstrap_builtin_packs", "load_declared_packs"]
