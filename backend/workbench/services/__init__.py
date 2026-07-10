"""Service layer: orchestration/aggregation logic that knows nothing about HTTP.

Sits between the http/ routers and the repository/ + domain layers. Functions
here take plain values (paths, dicts) and return plain values; they never touch
FastAPI request/response objects. Extracted from api.py in v1.6.10 (D1).
"""
