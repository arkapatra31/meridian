"""Shared types for the orchestrator package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from graph_engine.leiden_clustering import ClusterResult
from graph_engine.networkX_graph_builder import GraphBuildResult
from hybrid_parsing.codebase_parser.models import ParseResult
from ingestion_layer.repo_cache.clone_repo import CloneResult

Mode = Literal["FULL", "PATCH"]


@dataclass(frozen=True)
class OrchestrationResult:
    repo_url: str
    branch: str
    mode: Mode
    clone: CloneResult | None  # populated when mode == "FULL"
    tree: ParseResult | None  # parse tree from C4a/C4b
    tree_id: str | None  # populated once the tree is indexed (C4c)
    graph: GraphBuildResult | None  # populated once C5a has run
    graph_id: str | None  # populated once the graph is persisted (C8 stub)
    cluster: ClusterResult | None  # populated once C5b has clustered the graph
