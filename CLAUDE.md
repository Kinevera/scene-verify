# scene-verify Claude Code entrypoint

@AGENTS.md

`AGENTS.md` is the single workflow authority. This file adds no policy of its own; it only maps
that policy onto this harness.

- Model tiers map as in SceneForge (maintainer ruling, 2026-09-24): every subagent runs on Opus
  (Agent tool `model: "opus"`), except mechanical context collection, which runs on Sonnet
  (`model: "sonnet"`) with the orchestrator spot-checking every load-bearing claim. Never launch
  a subagent without an explicit `model`.
- The gated actions in `AGENTS.md` are prompts through `.claude/settings.json`
  (`permissions.ask` and `permissions.deny`). SceneForge's command-parsing gate hook is not
  ported here, so a compound or wrapped spelling of a gated command is not caught: spell gated
  commands literally. A declined prompt is the maintainer's decision.
- Audits use `.audit/local/` and handoffs `.agent/local/`, both ignored.
