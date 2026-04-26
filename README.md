# Meridian

> A remote-first, agent-powered code knowledge graph builder.

Point Meridian at any GitHub repository and get back an interactive, queryable knowledge graph — no local install required. Built with the Claude Code Agent SDK, tree-sitter, NetworkX, and Leiden clustering.

## Features

- **Zero install for end users** — just provide a GitHub URL (and a PAT for private repos).
- **Two-pass parsing** — tree-sitter for deterministic AST extraction across 25 languages, agent reasoning for surgical resolution of ambiguous edges.
- **Differential updates** — incremental graph patches in seconds via a built-in diff engine; no full rebuilds.
- **Graph-grounded QnA** — answers cite specific nodes and files, not hallucinated references.
- **Interactive visualization** — WebGL-rendered force graph with semantic zoom, community coloring, and confidence-weighted edges.

## Status

Early-stage. Proprietary — All Rights Reserved. See [LICENSE](LICENSE).
