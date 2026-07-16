"""Deterministic local-only fixtures for development and browser smoke tests."""

from .agent_navigation import AgentNavigationSmokeFixture, seed_agent_navigation_fixture

__all__ = ["AgentNavigationSmokeFixture", "seed_agent_navigation_fixture"]
