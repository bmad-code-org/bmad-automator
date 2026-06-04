# Maintainer Review Gate

This gate exists to catch the class of regressions that recent maintainer review
threads on the TEA workflow refactor exposed before asking for another PR pass.

## Boundaries

This is intentionally verification-only scope:

- dedicated invariant tests in standalone files
- dedicated resume-matrix coverage in a standalone file
- dedicated smoke-style runners that can be called explicitly

It should not expand product behavior by itself.

## Required Invariants

Before asking for a new maintainer review, check:

1. Pinned policy is authoritative.
2. Invalid policy/state fails closed.
3. Skipped steps do not write progress.
4. Resume restarts at the persisted token, not an earlier TEA step.
5. Standard mode stays isolated from TEA-specific progress writes.
6. Markdown-rendered state rows and headers reject unsafe identifiers/labels.

## Standalone Verification Files

- `tests/test_policy_invariants.py`
- `tests/test_progress_invariants.py`
- `tests/test_resume_matrix.py`
- `scripts/run-smoke-policy-invariants.py`
- `scripts/run-smoke-resume-matrix.py`

## Suggested Local Gate

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest \
  tests.test_policy_invariants \
  tests.test_progress_invariants \
  tests.test_resume_matrix
```

Optional smoke-style wrappers:

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 scripts/run-smoke-policy-invariants.py
PYTHONPATH=skills/bmad-story-automator/src python3 scripts/run-smoke-resume-matrix.py
```

## Relationship To PR 32

PR 32 is the direction for stronger deterministic live-run validation. These
standalone files are a bounded follow-up that starts encoding maintainer repros
locally without widening the product implementation scope.
