"""Local repository intelligence and context selection for coding agents."""

from middle_man.gateway.compact import CompactionResult, OutputCompactor
from middle_man.gateway.config import GatewayConfig
from middle_man.gateway.context_builder import ContextBuilder, ContextSettings
from middle_man.gateway.context_models import ContextMode, ContextPack, ExpansionRequest, SourceExcerpt
from middle_man.gateway.git_diff import GitDiffReader
from middle_man.gateway.indexer import RepositoryIndexer
from middle_man.gateway.relevance import ContextQuery, RelevanceEngine
from middle_man.gateway.secrets import SecretRedactor
from middle_man.gateway.tokens import HeuristicTokenEstimator, TokenEstimator

__all__ = [
    "GatewayConfig", "RepositoryIndexer", "ContextQuery", "RelevanceEngine",
    "ContextBuilder", "ContextSettings", "ContextMode", "ContextPack", "SourceExcerpt",
    "ExpansionRequest", "GitDiffReader", "OutputCompactor", "CompactionResult",
    "SecretRedactor", "TokenEstimator", "HeuristicTokenEstimator",
]