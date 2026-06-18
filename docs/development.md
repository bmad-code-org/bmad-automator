# Development

This doc covers local verification, smoke testing, packaging, and release steps for this repo itself.

## Local Verify

Primary checks:

```bash
npm run verify
PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help
```

`npm run verify` expands to:

- `npm run test:python`
- `npm run version:check`
- `npm run pack:assert`
- `npm run test:cli`
- `npm run smoke:contracts`
- `npm run smoke:modes`
- `npm run test:smoke`

Run `npm run smoke:deterministic-full` separately before release when prepared
repo reset, install identity, create, dev-loop, and finish-loop coverage is
needed.

## Smoke Test Coverage

The smoke suite validates:

- installer behavior
- packed `npx` install behavior from the generated tarball
- required and optional dependency handling
- legacy backup behavior
- installed skill layout
- installed runtime policy, prompt templates, and parse contracts
- prompt-building behavior for Claude and Codex child sessions

## External Automator Smoke Prep

Prepare the pinned `bma-d/gunz` smoke project in the ignored `.smoke/`
workspace:

```bash
npm run smoke:prepare -- --reset
```

This clones only the `bmad-smoke-test` branch, checks out
`fca6470d329668019dace305b5f0f3c9b62cb113`, installs BMAD core and BMM with
`bmad-method@next`, then installs the project-local automator into that target
project. The script leaves `.smoke/SMOKE_NEXT_STEPS.md` with the exact manual
Claude Code entrypoint for the semi-automated smoke run.

## Repo Verification Flow

```mermaid
flowchart TD
    A["Edit installer, skills, or runtime"] --> B["Run npm run test:python"]
    B --> C["Run npm run pack:assert"]
    C --> D["Run npm run smoke:contracts + smoke:modes"]
    D --> E["Run npm run verify"]
    E --> F["Run npm run smoke:deterministic-full before release"]
```

## Packaging Surface

Important package parts:

- `bin/bmad-story-automator`
- `install.sh`
- `skills/`
- `skills/bmad-story-automator/`
- `README.md`
- `ref.png`

The published package bundles the root `skills/` tree. The main skill contains the Python runtime source, so copied skills and npm installs use the same files.

## Runtime Entry During Development

The shell wrapper used in installed projects is mirrored in this repo:

```text
skills/bmad-story-automator/scripts/story-automator
```

It runs:

```text
python3 -m story_automator
```

with `PYTHONPATH` pointed at `skills/bmad-story-automator/src`.

## Legacy Env Compatibility

For one release cycle, fresh orchestration starts still honor:

- `MAX_REVIEW_CYCLES`
- `MAX_CRASH_RETRIES`

Those values are resolved once during snapshot creation. Resume paths read the pinned snapshot, not the current shell env. Prefer `_bmad/bmm/story-automator.policy.json` for new configuration changes.

## What To Re-Check After Runtime Changes

If you change:

- `commands/tmux.py`: re-check spawn, command building, monitor behavior, Codex vs Claude handling
- `commands/orchestrator.py`: re-check state summary, marker behavior, sprint-status verification
- `install.sh`: re-check dependency validation, copy layout, backups, shim cleanup
- skill step files: re-check docs, prompts, and smoke expectations

## Release

Publish steps:

- `npm adduser`
- `npm publish`

Recommended release checklist:

1. `npm run verify`
2. `npm run smoke:deterministic-full`
3. use `secrets` skill for npm auth material; search exact key names, then `secrets load <KEY>` into the publish shell; never print token values
4. inspect the package dry-run output
5. confirm README and docs match shipped behavior
6. publish

For BMAD Method stable tags, preview tags, registry `next`, and npm dist-tags,
use [Versioning And Release Channels](./versioning.md).

## Read Next

- [Installation And Layout](./installation-and-layout.md)
- [CLI Reference](./cli-reference.md)
- [Versioning And Release Channels](./versioning.md)
