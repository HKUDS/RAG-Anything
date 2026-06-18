# -*- coding: utf-8 -*-
"""
RAG-Anything Services Sub-Package — Service Layer.

Layer: Service
Primary Responsibility: Business orchestration, shared state management,
    cross-module coordination, WebSocket broadcasting.
Key Dependencies: raganything (Core), raganything.config, lightrag

Architecture: Router -> Service -> Core -> Infrastructure
"""

# Service modules are imported lazily to avoid circular deps.
# Import directly from sub-modules:
#   from raganything.services.kb_service import create_kb, get_kb, delete_kb
#   from raganything.services.ws_service import ws_broadcast, emit_progress
#   from raganything.services.state_service import state_service

__all__ = [
    # kb_service
    "create_kb",
    "get_kb",
    "delete_kb",
    "list_kbs",
    "kb_instances",
    "active_kb",
    # ws_service
    "ws_broadcast",
    "emit_progress",
    "ws_clients",
    "# state_service",
    "state_service",
    # auth (migrated from root)
    # agent_manager (migrated from root)
]
