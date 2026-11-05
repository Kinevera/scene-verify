# scene-verify agent instructions

This file is the single workflow authority for agent and contributor sessions in this
repository. `CLAUDE.md` points here and adds no policy. Keep it concise and durable; session notes
and audit runs live under the ignored `.agent/local/` and `.audit/local/` roots, never here.

scene-verify holds the Cybernetic scene verifier in two parts released under one version: the
`scene_verify/1` contract (`packages/contract`, the verdict schema and its validation, standard
library only) and the engine (`packages/engine`, the geometry and Isaac Sim checks that grade a
scene and produce a verdict). SceneForge's API pins the contract; SceneForge's verify stage worker
and RoboEval's PackingBench pin the engine (SceneForge sceneforge-0009, scene-verify-0001).

## Document ownership

| Document | Job |
| --- | --- |
| `AGENTS.md` | Workflow authority: rules, gates, validation, git, review |
| `README.md` | What the parts are, how to install and run them, and their status |
| `docs/adr/` | Decisions, indexed in `docs/adr/README.md`; an unrecorded decision is not a decision |
| `docs/` | The verifier's design and measurement notes, moved from RoboEval |

## First reads

1. `AGENTS.md`, then `README.md`.
2. `docs/adr/README.md` and the records the task touches.
3. The package and tests nearest the change.

## Binding rules

1. **Docs match reality.** Claims about runs use the status vocabulary: designed, built, ran on
   the rig, ran in production.
2. **The contract is an interface.** A change to the verdict shape or to the validator's rules is
   a contract change: it needs a record in `docs/adr/` and a line in the release notes, because
   SceneForge pins the contract and fails closed on what it cannot read.
3. **The contract stays dependency-free.** `scene_verify_contract` imports only the standard
   library; the engine imports nothing from RoboEval or SceneForge.
4. **Grading is behavior.** Gate logic, thresholds and the verdict a scene receives change only
   on purpose, with the evidence for the change in the PR.
5. **An unrecorded decision is a review blocker.** When the docs do not settle a question about
   the contract, grading semantics, packaging or release, ask the maintainer one question at a
   time with a recommended answer, then record the ruling.
6. **Never print or commit** tokens, private endpoints, customer capture bytes, raw media or
   base64 payloads, or machine-specific absolute paths.

## Gated actions (fail closed)

Each needs the maintainer's explicit approval for that specific action: `git push`, opening,
merging or closing a PR, deleting a remote branch, any GitHub write (comments, reviews, issues,
releases, tags pushed to the remote, labels, settings, secrets, `gh api` with a mutating method),
any Docker lifecycle command, and any Isaac Sim or GPU run. Force pushes are refused.
`.claude/settings.json` turns these into prompts in Claude Code; in every other harness they are
instruction-only, apart from the git hooks below. A declined prompt is the maintainer's decision.

## Validation

From the repository root, on every change: `make check` (ruff check, ruff format check, mypy,
lock drift) and `make test`. When `.githooks/` or `scripts/` change, also `make hooks-check` and
`scripts/setup-dev.sh --check`. CI runs the same targets. Tests need no GPU and no Isaac Sim;
`pxr` is real (`usd-core`). A runner change is checked on Isaac Sim only on a GPU host, with
approval, and the PR records what ran where.

## Git workflow

- `dev` is the integration branch and the default; `main` receives `dev` only through a promotion
  PR. Releases are annotated tags `vX.Y.Z` on `main` with a GitHub release; both distributions
  carry that version, and the engine's `VERIFIER_VERSION` equals it.
- Topic branches are `type/kebab-slug` cut from `dev`. Merge commits only; never squash or rebase
  a PR, and never rewrite `dev` or `main`.
- Conventional commits, `type(scope): subject`, enforced by `.githooks/commit-msg`; the
  `pre-push` hook refuses direct pushes to `dev` and `main` and non-fast-forward pushes to any
  branch, and runs `make check` on the checked-out tree. `scripts/setup-dev.sh` installs the hooks.
- Only the maintainer approves a merge, per PR, naming it once it exists.

## Review

Every change reaching `dev` gets one review round before push approval: a primary reviewer and a
blind peer on the final diff, then a final-diff check of any fix pass. The agent that wrote a
change does not review it. The maintainer accepts, rejects or defers each finding; the fix pass
covers blocker, high and security findings and anything that stops the change working, and the
rest become issues.

## Agent model policy

Mechanical context collection runs on the fast tier and is spot-checked by the orchestrator;
everything else a subagent does (implementation, review, verification) runs on the strong tier.
Harness model names live in `CLAUDE.md`.
