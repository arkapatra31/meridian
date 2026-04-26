# Pull Request

## Summary

<!-- One or two sentences: what does this PR change and why? -->

## Component(s) Touched

<!-- Tick all that apply -->

- [ ] C1 API Gateway (FastAPI)
- [ ] C2 GitHub MCP / C3 Repo Cache
- [ ] C4 Agent SDK Orchestrator
- [ ] C5 Tree-sitter (Pass 1)
- [ ] C6 Agent Reasoning (Pass 2)
- [ ] C7 Diff Engine
- [ ] C8 Graph Builder / C9 Leiden / C10 Graph Store
- [ ] C11 QnA Agent
- [ ] C12 React Frontend
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
