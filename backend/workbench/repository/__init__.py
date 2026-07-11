"""Repository layer: pure filesystem reads over a project's run directory.

No FastAPI, no orchestration, no event/SSE state — just resolve paths and read
JSON/artifacts off disk, raising WorkbenchAPIError for not-found / invalid-path.
Extracted from api.py in v1.6.10 (D1 decomposition).
"""
