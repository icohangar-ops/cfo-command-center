"""
CFO Command Center — Entity Registry Module

Manages multiple legal entities / business units within the
CFO Command Center.
"""

from .entity import Entity, EntityRegistry
from .manager import MultiEntityManager

__all__ = ["Entity", "EntityRegistry", "MultiEntityManager"]
