#!/usr/bin/env bash
# Regression battery for .githooks/commit-msg and .githooks/pre-push, adapted from SceneForge's.
# Each case states the expected exit (pass or fail) and the input. Run: make hooks-check
# The ref-policy pre-push cases run in a throwaway repository with
# SCENE_VERIFY_SKIP_PREPUSH_CHECK=1, which exits before the pushed-ref and dirty-tree checks and
# the gates. The dirty-tree and pushed-ref cases run without it and assert on the hook's stderr,
# because the real gates are absent there (that repository has no Makefile). The gate cases give
# a throwaway repository a stub Makefile whose `check` target fails or passes, proving the hook
# refuses a push when the gates fail and allows it when they pass; the real gates (ruff, mypy,
# lock drift) are exercised by `make check`, not here.
set -uo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
hooks="$here/.githooks"
fail=0; n=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

expect() {
  local expected="$1" label="$2" rc="$3"
  n=$((n+1))
  local got="pass"
  [ "$rc" -ne 0 ] && got="fail"
  if [ "$got" != "$expected" ]; then
    echo "FAIL expected=$expected got=$got :: $label"; fail=$((fail+1))
  fi
}

# --- commit-msg ---------------------------------------------------------------------------
msg() {
  local expected="$1" subject="$2"
  printf '%s\n' "$subject" > "$tmp/COMMIT_EDITMSG"
  bash "$hooks/commit-msg" "$tmp/COMMIT_EDITMSG" 2>/dev/null
  expect "$expected" "commit-msg: $subject" $?
}
msg pass 'feat(contract): reject a verdict whose overall status hides a failing gate'
msg pass 'fix(engine): fall back to the aabb floor when penetration depth is nan'
msg pass 'docs(readme): state how to pin the contract by tag'
msg pass 'chore(import): import the scene verifier from roboeval at ffda3a96'
msg pass 'ci(workflow): run the hook battery'
msg pass 'test(engine): cover the settle window floor [R1-01 R1-02]'
msg pass 'docs(adr): `docs/adr/README.md` indexes scene-verify-0001'
msg pass 'Merge pull request #1 from Cybernetic-EAI/feat/import-scene-verifier'
msg pass 'Revert "feat(contract): reject a verdict whose overall status hides a failing gate"'
msg pass 'fixup! feat(engine): report verifier_version 0.3.0'
msg pass 'docs(readme): name both packages and the tag they install from [PR1-001 PR1-002 PR1-003 PR1-004 FD-A FD-B FD-C]'
msg fail 'update validation logic'
msg fail 'feat: reject a malformed verdict'
msg fail 'feat(contract) reject a malformed verdict'
msg fail 'feat(contract): Reject a malformed verdict'
msg fail 'feature(contract): reject a malformed verdict'
msg fail 'feat(Contract): reject a malformed verdict'
msg pass 'build(deps): bump ruff'
msg pass 'refactor(engine): split the capture layer'
msg pass 'perf(engine): sample fewer surface points'
msg pass 'style(engine): reorder imports'
msg pass 'feat(contract)!: drop the scene_verify/1 prefix rule'
msg pass 'amend! feat(engine): report verifier_version 0.3.0'
msg pass "Merge branch 'dev' into feat/x"
msg pass "Merge remote-tracking branch 'origin/dev'"
msg pass "Merge tag 'v0.3.0'"
msg pass "Merge commit 'abc123' into feat/x"
msg pass "Merge branches 'a' and 'b' into feat/x"
msg pass "Merge tags 'v1' and 'v2'"
msg pass "Merge remote-tracking branches 'origin/a' and 'origin/b'"
msg pass 'Revert "feat(engine): report verifier_version 0.3.0"'
msg fail 'Revert everything'
msg pass 'Reapply "feat(engine): report verifier_version 0.3.0"'
msg fail 'Reapply everything'
msg fail 'Merge stuff'
msg fail 'feat(contract,engine): share the status order'
msg fail 'feat(engine.runners): add the usd runner'
msg fail 'feat(scene_verify): add the usd runner'
msg fail 'feat(engine/runners): add the usd runner'
msg fail 'feat(contract)! : drop the prefix rule'
msg fail 'feature(contract)!: drop the prefix rule'
msg fail ''
msg fail 'feat(engine): this subject keeps going well past one hundred characters so the hook has to refuse it here'
# Comment lines before the subject are skipped, as git would strip them.
printf '# a comment\n\nfeat(engine): report verifier_version 0.3.0\n' > "$tmp/COMMIT_EDITMSG"
bash "$hooks/commit-msg" "$tmp/COMMIT_EDITMSG" 2>/dev/null; expect pass "commit-msg: comment then subject" $?

# --- pre-push -----------------------------------------------------------------------------
repo="$tmp/repo"
git init -q "$repo"
git -C "$repo" config user.email test@example.com
git -C "$repo" config user.name test
git -C "$repo" commit -q --allow-empty -m 'chore(init): root'
base="$(git -C "$repo" rev-parse HEAD)"
git -C "$repo" commit -q --allow-empty -m 'chore(init): second'
tip="$(git -C "$repo" rev-parse HEAD)"
git -C "$repo" checkout -q -b other "$base"
git -C "$repo" commit -q --allow-empty -m 'chore(init): diverged'
diverged="$(git -C "$repo" rev-parse HEAD)"
zero="0000000000000000000000000000000000000000"

push() {
  local expected="$1" label="$2" stdin="$3"
  shift 3
  ( cd "$repo" && printf '%s\n' "$stdin" | env SCENE_VERIFY_SKIP_PREPUSH_CHECK=1 "$@" bash "$hooks/pre-push" origin https://example.invalid/r.git ) >/dev/null 2>&1
  expect "$expected" "pre-push: $label" $?
}
push fail "direct push to dev"            "refs/heads/topic $tip refs/heads/dev $base"
push fail "direct push to main"           "refs/heads/topic $tip refs/heads/main $base"
push fail "new branch named dev"          "refs/heads/dev $tip refs/heads/dev $zero"
push fail "delete dev"                    "$zero $zero refs/heads/dev $base"
push pass "fast-forward topic"            "refs/heads/topic $tip refs/heads/topic $base"
push pass "create topic"                  "refs/heads/topic $tip refs/heads/topic $zero"
push pass "delete topic"                  "(delete) $zero refs/heads/topic $tip"
push pass "unchanged topic"               "refs/heads/topic $tip refs/heads/topic $tip"
push fail "non-fast-forward topic"        "refs/heads/other $diverged refs/heads/topic $tip"
push pass "non-fast-forward topic allowed" "refs/heads/other $diverged refs/heads/topic $tip" SCENE_VERIFY_ALLOW_NON_FF_PUSH=1
push fail "remote tip unknown locally"    "refs/heads/topic $tip refs/heads/topic 1111111111111111111111111111111111111111"
push pass "nothing to push"               ""
push fail "dev among several refs"        "refs/heads/topic $tip refs/heads/topic $base
refs/heads/topic $tip refs/heads/dev $base"
# SceneForge's escape names do nothing here.
push fail "SceneForge's non-ff escape is not honoured" "refs/heads/other $diverged refs/heads/topic $tip" SCENEFORGE_ALLOW_NON_FF_PUSH=1

# --- pre-push dirty-tree check (no SCENE_VERIFY_SKIP_PREPUSH_CHECK) -------------------------
dirty="$tmp/dirty"
git init -q "$dirty"
git -C "$dirty" config user.email test@example.com
git -C "$dirty" config user.name test
printf 'one\n' > "$dirty/tracked.txt"
git -C "$dirty" add tracked.txt
git -C "$dirty" commit -q -m 'chore(init): root'
dbase="$(git -C "$dirty" rev-parse HEAD)"
git -C "$dirty" commit -q --allow-empty -m 'chore(init): second'
dtip="$(git -C "$dirty" rev-parse HEAD)"
dline="refs/heads/topic $dtip refs/heads/topic $dbase"

# Runs the hook in the dirty-tree repository with the given env assignments; stderr lands in
# $tmp/prepush.err so the caller can prove which check refused.
push_gates() {
  local stdin="$1"
  shift
  ( cd "$dirty" && printf '%s\n' "$stdin" | env -u SCENE_VERIFY_SKIP_PREPUSH_CHECK "$@" bash "$hooks/pre-push" origin https://example.invalid/r.git ) >/dev/null 2>"$tmp/prepush.err"
}
has_err() { grep -q -- "$1" "$tmp/prepush.err"; }

# (a) a modified tracked file is refused before the gates run.
printf 'two\n' > "$dirty/tracked.txt"
push_gates "$dline"; rc=$?
expect fail "pre-push: dirty tracked file refused" $rc
has_err "uncommitted"; expect pass "pre-push: dirty refusal names uncommitted changes" $?
has_err "running the fast gates"; [ $? -ne 0 ]; expect pass "pre-push: dirty refusal comes before the gates" $?
# A staged change is refused the same way.
git -C "$dirty" add tracked.txt
push_gates "$dline"; rc=$?
expect fail "pre-push: staged tracked change refused" $rc
has_err "uncommitted"; expect pass "pre-push: staged refusal names uncommitted changes" $?
# (c) the skip escape still passes with a dirty tree.
push_gates "$dline" SCENE_VERIFY_SKIP_PREPUSH_CHECK=1
expect pass "pre-push: dirty tree with SCENE_VERIFY_SKIP_PREPUSH_CHECK=1" $?
git -C "$dirty" reset -q --hard HEAD

# (b) only an untracked file: warned, not refused; the hook reaches the gates.
printf 'x\n' > "$dirty/untracked.txt"
push_gates "$dline"
has_err "untracked files are present"; expect pass "pre-push: untracked file draws the warning" $?
has_err "uncommitted"; [ $? -ne 0 ]; expect pass "pre-push: untracked file is not refused as uncommitted" $?
has_err "running the fast gates"; expect pass "pre-push: untracked file reaches the gates" $?
rm -f "$dirty/untracked.txt"

# (d) a tree without a Makefile cannot run the gates, so the push is refused.
push_gates "$dline"; rc=$?
expect fail "pre-push: a tree without the Makefile is refused" $rc
has_err "running the fast gates"; expect pass "pre-push: the missing-Makefile refusal comes from the gates" $?

# --- pre-push pushed-ref check (no SCENE_VERIFY_SKIP_PREPUSH_CHECK) --------------------------
# (a) a ref whose commit is not HEAD is refused from a clean tree, before the gates.
push_gates "refs/heads/old $dbase refs/heads/old $zero"; rc=$?
expect fail "pre-push: ref other than HEAD refused" $rc
has_err "checked-out"; expect pass "pre-push: non-HEAD refusal names the checked-out tree" $?
has_err "running the fast gates"; [ $? -ne 0 ]; expect pass "pre-push: non-HEAD refusal comes before the gates" $?
# (b) a deletion-only push passes from a dirty tree, without the dirty-tree refusal or gates.
printf 'three\n' > "$dirty/tracked.txt"
push_gates "(delete) $zero refs/heads/topic $dtip"; rc=$?
expect pass "pre-push: deletion-only push from a dirty tree" $rc
has_err "uncommitted"; [ $? -ne 0 ]; expect pass "pre-push: deletion-only push skips the dirty-tree refusal" $?
has_err "running the fast gates"; [ $? -ne 0 ]; expect pass "pre-push: deletion-only push skips the gates" $?
git -C "$dirty" reset -q --hard HEAD
# (c) empty stdin passes without the gates.
push_gates ""; rc=$?
expect pass "pre-push: nothing to push without the skip escape" $rc
has_err "running the fast gates"; [ $? -ne 0 ]; expect pass "pre-push: nothing to push skips the gates" $?

# --- pre-push fast gates (stub Makefile) ----------------------------------------------------
# Builds a clean throwaway repository whose root Makefile `check` target runs the given recipe;
# push_stub then pushes HEAD with the skip escape unset.
gates_repo() {
  local dir="$1" recipe="$2"
  git init -q "$dir"
  git -C "$dir" config user.email test@example.com
  git -C "$dir" config user.name test
  printf 'check:\n\t%s\n' "$recipe" > "$dir/Makefile"
  git -C "$dir" add Makefile
  git -C "$dir" commit -q -m 'chore(init): stub gates'
}
push_stub() {
  local dir="$1" head
  head="$(git -C "$dir" rev-parse HEAD)"
  ( cd "$dir" && printf '%s\n' "refs/heads/topic $head refs/heads/topic $zero" | env -u SCENE_VERIFY_SKIP_PREPUSH_CHECK bash "$hooks/pre-push" origin https://example.invalid/r.git ) >/dev/null 2>"$tmp/prepush.err"
}
gates_repo "$tmp/gates-red" '@exit 1'
push_stub "$tmp/gates-red"; rc=$?
expect fail "pre-push: failing gates block the push" $rc
has_err "running the fast gates"; expect pass "pre-push: the failing-gates refusal comes from the gates" $?
gates_repo "$tmp/gates-green" '@true'
push_stub "$tmp/gates-green"; rc=$?
expect pass "pre-push: passing gates allow the push" $rc
has_err "running the fast gates"; expect pass "pre-push: the passing push ran the gates" $?
# The gates run from the repository root even when the push starts in a subdirectory.
mkdir -p "$tmp/gates-green/sub"
head="$(git -C "$tmp/gates-green" rev-parse HEAD)"
( cd "$tmp/gates-green/sub" && printf '%s\n' "refs/heads/topic $head refs/heads/topic $zero" | env -u SCENE_VERIFY_SKIP_PREPUSH_CHECK bash "$hooks/pre-push" origin https://example.invalid/r.git ) >/dev/null 2>"$tmp/prepush.err"
expect pass "pre-push: a push from a subdirectory runs the root gates" $?

# --- pre-push annotated tags (stub Makefile whose check passes) ------------------------------
# An annotated tag is pushed as its tag object; the hook peels it to the tagged commit before
# comparing with HEAD.
tags="$tmp/gates-tags"
gates_repo "$tags" '@true'
tbase="$(git -C "$tags" rev-parse HEAD)"
git -C "$tags" commit -q --allow-empty -m 'chore(init): tagged tip'
thead="$(git -C "$tags" rev-parse HEAD)"
git -C "$tags" tag -a v1 -m v1
git -C "$tags" tag -a v0 -m v0 "$tbase"
tag_head="$(git -C "$tags" rev-parse v1)"
tag_old="$(git -C "$tags" rev-parse v0)"
push_tags() {
  ( cd "$tags" && printf '%s\n' "$1" | env -u SCENE_VERIFY_SKIP_PREPUSH_CHECK bash "$hooks/pre-push" origin https://example.invalid/r.git ) >/dev/null 2>"$tmp/prepush.err"
}
# (a) an annotated tag at HEAD passes and the gates run.
[ "$tag_head" != "$thead" ]; expect pass "pre-push: the annotated tag is pushed as a tag object" $?
push_tags "refs/tags/v1 $tag_head refs/tags/v1 $zero"; rc=$?
expect pass "pre-push: annotated tag at HEAD passes" $rc
has_err "running the fast gates"; expect pass "pre-push: annotated tag at HEAD runs the gates" $?
# (b) an annotated tag at another commit is refused before the gates.
push_tags "refs/tags/v0 $tag_old refs/tags/v0 $zero"; rc=$?
expect fail "pre-push: annotated tag at another commit refused" $rc
has_err "checked-out commit"; expect pass "pre-push: non-HEAD tag refusal names the checked-out commit" $?
has_err "running the fast gates"; [ $? -ne 0 ]; expect pass "pre-push: non-HEAD tag refusal comes before the gates" $?
# (c) a branch and the annotated tag, both at HEAD, pass together.
push_tags "refs/heads/topic $thead refs/heads/topic $zero
refs/tags/v1 $tag_head refs/tags/v1 $zero"; rc=$?
expect pass "pre-push: branch plus annotated tag at HEAD passes" $rc
has_err "running the fast gates"; expect pass "pre-push: branch plus annotated tag at HEAD runs the gates" $?

echo "$n cases, $fail failures"
[ "$fail" -eq 0 ]
