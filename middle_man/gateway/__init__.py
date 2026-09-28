"""Local repository intelligence for coding-agent context discovery."""

from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine

__all__ = ["GatewayConfig", "RepositoryIndexer", "ContextQuery", "RelevanceEngine"]
