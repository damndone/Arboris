"""HTTP layer: FastAPI ``APIRouter`` clusters + request/response models.

Thin — each module parses a request, calls into ``services``/``repository``, and
shapes the response (raising ``WorkbenchAPIError`` for failures). No business
logic lives here. Routers are mounted onto the app in ``workbench.app``.

Introduced in v1.6.10 (D1 decomposition, Phase 4).
"""
