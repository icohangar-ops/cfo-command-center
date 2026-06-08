"""
CFO Command Center — Consolidation Agent

Entry point for the cross-entity consolidation module.
Re-exports from the consolidated __init__.py to avoid confusion.
"""

from .agent import ConsolidationAgent

__all__ = ["ConsolidationAgent"]
