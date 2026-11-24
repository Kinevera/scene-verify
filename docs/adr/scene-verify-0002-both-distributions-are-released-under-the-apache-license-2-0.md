# scene-verify-0002: Both distributions are released under the Apache License 2.0

- **Status:** Accepted
- **Date:** 2026-11-24
- **Scope:** The licence of this repository and of the `scene-verify-contract` and `scene-verify`
  distributions, how the licence is declared, and who holds the copyright

## Context

The amendment of 2026-11-08 to scene-verify-0001 made this repository public so that consumers can
install both distributions from git by tag. No licence was chosen at the time: the README said
"No license has been chosen yet. Until one is added, all rights are reserved", and both
`pyproject.toml` files declared `license = { text = "Proprietary" }`. A public repository with no
licence can be read but not legally reused, which defeats the reason it was made public.

Kinevera is also preparing a proposal to ARIA's Standards and Benchmarks for Dexterous Robotics
call (deadline 2026-12-01). That call scores openness and reuse, and the proposal lists this
repository among Kinevera's open outputs. The maintainer ruled on 2026-11-24 to release it under
Apache-2.0. The copyright holder is Kinevera Robotics Ltd (Companies House 17437973), checked on
the Companies House register on 2026-11-24.

## Decision

1. The repository and both distributions are licensed under the Apache License, Version 2.0.
2. Each distribution declares the SPDX expression `license = "Apache-2.0"` with
   `license-files = ["LICENSE"]` (PEP 639, supported by the pinned `uv_build>=0.12.17,<0.13`), and
   carries the unmodified licence text at `packages/<name>/LICENSE`. The repository root carries
   the same text so GitHub detects it. The three copies are byte-identical to
   https://www.apache.org/licenses/LICENSE-2.0.txt.
3. The README's License section names the holder: "Copyright 2026 Kinevera Robotics Ltd". Both
   distributions name `Kinevera Robotics Ltd` as author.
4. There is no NOTICE file and no per-file licence header. The repository contains no third-party
   code that requires attribution, and the README and the LICENSE files are the licence statement.

## Consequences

- Anyone can use, modify and redistribute the contract and the engine, including commercially,
  with a patent grant from each contributor. Consumers can pin a tag without a separate agreement.
- The licence grant is only as good as Kinevera's title to the code. Code written before the
  contributors' IP assignments to Kinevera Robotics Ltd are signed is not cleanly Kinevera's, so
  this change merges only once those assignments cover every author of the code it releases
  (the commit authors and the authors of the verifier work moved from RoboEval under
  scene-verify-0001).
- The three LICENSE copies can drift apart. Nothing checks them automatically; a change to one is
  a change to all three, made in one commit.
- Releasing under Apache-2.0 cannot be withdrawn for copies already distributed. A later change of
  licence applies only to later versions.
- Prose in the README and AGENTS.md still calls the company "Cybernetic". That is a product and
  history name, not the copyright holder, and is left for a separate change.

## Alternatives considered

- **MIT:** shorter and equally permissive, but gives no express patent grant, which matters for a
  verifier that other organisations are asked to build on.
- **Keep it unlicensed:** keeps every right, but leaves a public repository nobody may reuse and
  contradicts the reason it was made public.
- **A non-commercial or source-available licence:** protects commercial use, but blocks the
  industrial adoption the verifier and the ARIA proposal both aim for.
- **NOTICE file and per-file headers:** the Apache appendix suggests them, but they add upkeep to
  every source file without changing the grant, and no third-party attribution needs a NOTICE.

## Revisit trigger

Third-party code that requires attribution enters the repository (add a NOTICE file), or a
contributor's IP assignment to Kinevera Robotics Ltd turns out not to cover code this repository
releases.
