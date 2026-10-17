# Architecture decision records

Decisions this repository owns: what the verifier contract and engine contain, how they are
packaged, versioned and released, and how the repository is worked on. Each record states the
context it was decided in, the decision, what it costs, what was rejected, and the concrete
condition that would reopen it. A decision that is not in a record is not a decision.

## Naming

Files are named `scene-verify-NNNN-<sentence-title-in-kebab>.md`, numbered from 0001 in this
repository's own sequence. Cite a record here as "scene-verify-NNNN" and a record from another
repository by its own prefix, for example SceneForge's "sceneforge-0009". Numbers are never
reused, and a superseded record stays in place with its status changed.

## Template

Every record carries a Status bullet, a Date bullet and a Scope bullet, then `## Context`,
`## Decision`, `## Consequences`, `## Alternatives considered` and `## Revisit trigger`, in that
order. Status is one of Proposed, Accepted, Superseded or Rejected. The revisit trigger is a
condition someone can check. Copy `TEMPLATE.md` to start a record.

## Index

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [scene-verify-0001](scene-verify-0001-the-verifier-moves-from-roboeval-as-a-contract-and-an-engine-released-under-one-tag.md) | The verifier moves from RoboEval as a contract and an engine released under one tag | Accepted | 2026-10-17 |
