"""Keyword search across graph nodes using BM25.

Each node is turned into a small "document" built from its identifier-style
fields (name, id, file, type) plus the names of its immediate neighbours.
Identifiers are split on camelCase / snake_case / path separators so a query
like "validate auth" can match `validate_token` or `AuthValidator`.

Scoring stack:
  1. BM25 over the tokenized corpus (rare terms dominate).
  2. Field weighting: name > id > neighbours > file > type.
  3. Structural boost: hubs (`is_god`) get a small bonus, orphans a small
     penalty.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_STOPWORDS = {
    "the", "and", "for", "what", "where", "which", "does", "this", "that",
    "with", "from", "into", "how", "why", "when", "who", "are", "was", "were",
    "use", "uses", "used", "call", "calls", "called", "function", "class",
    "method", "module", "file", "files", "code", "show", "find", "list",
    "tell", "give", "graph", "node", "nodes", "edge", "edges",
}

# Field weights — applied as token-repetition multipliers when building the
# per-node bag of words. Name is the strongest signal, type the weakest.
_FIELD_WEIGHTS: dict[str, int] = {
    "name": 3,
    "id": 2,
    "neighbours": 1,
    "file": 1,
    "type": 1,
}

# BM25 hyperparameters — standard defaults.
_K1 = 1.5
_B = 0.75


def _split_identifier(text: str) -> list[str]:
    """Split an identifier-shaped string into lowercase word tokens.

    Handles snake_case, kebab-case, dotted paths, slashes, camelCase, and
    PascalCase. The original token is kept alongside the splits so an exact
    substring like `validate_token` still scores when queried verbatim.
    """
    if not text:
        return []
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        out.append(raw.lower())
        for piece in _CAMEL_RE.split(raw):
            piece = piece.lower()
            if piece and piece != raw.lower():
                out.append(piece)
    return out


def _tokenize_query(query: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(query):
        for piece in [raw.lower(), *(_CAMEL_RE.split(raw))]:
            piece = piece.lower()
            if piece and piece not in _STOPWORDS and len(piece) > 1:
                tokens.append(piece)
    return tokens or [query.lower().strip()]


def _build_document(
    node: dict[str, Any],
    neighbour_names: list[str],
) -> list[str]:
    """Return the weighted token bag for a node."""
    bag: list[str] = []
    for field, weight in _FIELD_WEIGHTS.items():
        if field == "neighbours":
            value = " ".join(neighbour_names)
        else:
            value = str(node.get(field, "") or "")
        for tok in _split_identifier(value):
            bag.extend([tok] * weight)
    return bag


def _structural_multiplier(node: dict[str, Any]) -> float:
    if node.get("is_god"):
        return 1.3
    if node.get("is_orphan"):
        return 0.8
    return 1.0


def run(
    query: str,
    graph_data: dict[str, Any],
    *,
    top_k: int = 8,
    node_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return top-K BM25-scored nodes with pre-fetched direct neighbours.

    Each result dict contains:
        id, name, type, file, line_start, line_end, community, is_god,
        is_orphan, neighbours: list of {id, name, type, edge_type, direction}
    """
    nodes: list[dict] = graph_data.get("nodes", [])
    edges: list[dict] = graph_data.get("edges", [])

    by_id: dict[str, dict] = {n["id"]: n for n in nodes if "id" in n}

    # Adjacency map (used for both neighbour pre-fetch and document building).
    adj: dict[str, list[dict]] = {}
    for e in edges:
        s, t, et = e.get("source"), e.get("target"), e.get("type", "")
        conf = e.get("confidence", "")
        if s:
            adj.setdefault(s, []).append(
                {"id": t, "edge_type": et, "direction": "out", "confidence": conf}
            )
        if t:
            adj.setdefault(t, []).append(
                {"id": s, "edge_type": et, "direction": "in", "confidence": conf}
            )

    candidates = [n for n in nodes if not node_type or n.get("type") == node_type]
    if not candidates:
        return []

    # ── Build the BM25 corpus ────────────────────────────────────────────────
    documents: list[list[str]] = []
    for node in candidates:
        nid = node.get("id", "")
        nbr_names = [
            (by_id.get(nb["id"], {}) or {}).get("name") or nb["id"] or ""
            for nb in adj.get(nid, [])[:10]
        ]
        documents.append(_build_document(node, nbr_names))

    doc_lens = [len(d) for d in documents]
    avgdl = (sum(doc_lens) / len(doc_lens)) if doc_lens else 0.0
    n_docs = len(documents)

    # Document frequency for IDF.
    df: Counter[str] = Counter()
    for doc in documents:
        for tok in set(doc):
            df[tok] += 1

    keywords = _tokenize_query(query)

    def idf(term: str) -> float:
        # Standard BM25 IDF with the +1 smoothing that keeps it non-negative.
        n_qi = df.get(term, 0)
        return math.log((n_docs - n_qi + 0.5) / (n_qi + 0.5) + 1.0)

    # ── Score every candidate ────────────────────────────────────────────────
    scored: list[tuple[float, dict]] = []
    for node, doc, dl in zip(candidates, documents, doc_lens, strict=False):
        if not doc:
            continue
        tf = Counter(doc)
        score = 0.0
        for term in keywords:
            f = tf.get(term, 0)
            if f == 0:
                continue
            denom = f + _K1 * (1 - _B + _B * (dl / avgdl if avgdl else 1.0))
            score += idf(term) * (f * (_K1 + 1)) / denom
        if score <= 0:
            continue
        score *= _structural_multiplier(node)
        scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [n for _, n in scored[:top_k]]

    # ── Attach pre-fetched neighbours for the composer ───────────────────────
    results: list[dict[str, Any]] = []
    for node in top:
        nid = node.get("id", "")
        raw_nbrs = adj.get(nid, [])[:15]
        neighbours = []
        for nb in raw_nbrs:
            nb_node = by_id.get(nb["id"] or "", {})
            neighbours.append({
                "id": nb["id"],
                "name": nb_node.get("name", nb["id"]),
                "type": nb_node.get("type"),
                "edge_type": nb["edge_type"],
                "direction": nb["direction"],
            })
        results.append({
            "id": nid,
            "name": node.get("name"),
            "type": node.get("type"),
            "file": node.get("file"),
            "line_start": node.get("line_start"),
            "line_end": node.get("line_end"),
            "community": node.get("community"),
            "is_god": node.get("is_god", False),
            "is_orphan": node.get("is_orphan", False),
            "neighbours": neighbours,
        })

    return results
