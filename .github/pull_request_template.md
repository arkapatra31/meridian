# Pull Request

## Summary

<!-- One or two sentences: what does this PR change and why? -->

## Component(s) Touched

<!-- Tick all that apply -->

- [ ] C1 API Gateway (FastAPI)
- [ ] C2 Orchestrator
- [ ] C3 Ingestion (C3a Git Client / C3b GitHub MCP)
- [ ] C4 Hybrid Parser (C4a Tree-sitter / C4b Agent Reasoning / C4c Tree Indexer)
- [ ] C5 Graph Engine (C5a Graph Builder / C5b Leiden Clustering)
- [ ] C6 QnA Agent
- [ ] C7 React Frontend
- [ ] C8 Persistence (SQLite `meridian.db`)
- [ ] Infra / Docker / CI
- [ ] Docs only

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Performance
- [ ] Docs
- [ ] Chore / tooling

## Test Plan

<!-- How did you verify this? Commands run, manual steps, screenshots for UI. -->

- [ ] Unit tests pass (`pytest`)
- [ ] Manual smoke test
- [ ] Frontend verified in browser (if UI changes)

## Checklist

- [ ] Adheres to architecture rules in [CLAUDE.md](../CLAUDE.md) (no LSP, no DB, no direct Anthropic API, etc.)
- [ ] No secrets, PATs, or credentials committed
- [ ] No full-repo content sent to LLM (surgical tool calls only)
- [ ] CODEOWNERS review requested

## Related Issues

<!-- Closes #123, refs #456 -->
