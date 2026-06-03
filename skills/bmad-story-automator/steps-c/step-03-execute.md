---
name: 'step-03-execute'
description: 'Autonomous execution loop - create and dev stories'
nextStep: './step-03a-execute-review.md'
dataFileIndex: '../data/data-file-index.md'
scriptsDir: '../scripts/story-automator'
outputFolder: '{output_folder}/story-automator'
stateFilePattern: '{outputFolder}/orchestration-*.md'
outputFile: '{outputFolder}/orchestration-{epic_id}-{timestamp}.md'
retryStrategy: '../data/retry-fallback-strategy.md'
executionPatterns: '../data/execution-patterns.md'
subagentPrompts: '../data/subagent-prompts.md'
---

## 🚨 CRITICAL: Load Data File Index FIRST

**BEFORE ANY EXECUTION**, load and read `{dataFileIndex}` completely.
**DO NOT proceed until you have read the index and loaded the required files.**

---
Set: `scripts="{scriptsDir}"`

## 🚨 CRITICAL: CLI Contract Check (Interface Drift Guard)

Before running any story loop logic, verify required helper commands/flags still exist.

```bash
# Core command availability
"$scripts" tmux-wrapper --help >/dev/null
"$scripts" monitor-session --help >/dev/null
"$scripts" orchestrator-helper --help >/dev/null

# Required spawn contract: --command must exist
"$scripts" tmux-wrapper spawn --help | grep -q -- "--command"

# Build command contract must be available
"$scripts" tmux-wrapper build-cmd --help >/dev/null
```

If any check fails: **STOP and escalate immediately** with "helper CLI contract changed".

---

# Step 3: Execute Build Cycle

**Goal:** Autonomously execute all stories. Escalate only when decisions needed.
**Interaction mode:** Deterministic autonomous execution.

---

## Setup

Load from state document (located via `{stateFilePattern}`; output folder `{outputFolder}`; resolved path stored as `{outputFile}` for this run):
- `storyRange`, `currentStory`, `currentStep`
- `overrides` (skipAutomate, maxParallel)
- `customInstructions`
- pinned workflow policy snapshot

Resolve agent configuration using deterministic agents file (see `{retryStrategy}` for full function):
```bash
state_file="{outputFile}"
# resolve_agent_for_task "{task}" "$state_file" "{story_id}" -> sets primary_agent,fallback_agent
```

**IF resuming** (currentStory set): Skip to that point in loop.
**IF fresh**: Display "**Starting build cycle for {count} stories...**"

### Workflow Sequence Rule

The pinned workflow policy snapshot is authoritative for per-story task order.

- Standard default path: `create -> dev -> auto -> review`
- TEA v1 opt-in path: `create -> atdd -> dev -> test_automate -> test_review -> trace -> review`

Do not silently switch to TEA because TEA skills are installed. Only follow TEA steps when the pinned policy sequence explicitly includes them.

## 🚨 CRITICAL: Execution Patterns

**BEFORE executing any steps, read `{executionPatterns}` for:**
- FORBIDDEN patterns (never chain multiple workflow steps)
- REQUIRED patterns (verify state after each step)
- Monitoring failure fallback sequence

**Key rule:** Each step (create/dev/auto/review) MUST be executed and monitored separately. NEVER chain steps in loops.

## Story Loop

> **⚠️ SPAWN PATTERN - READ THIS:**
> Every `story-automator tmux-wrapper spawn` call **MUST** include `--command` with the built command:
> ```bash
> session=$("$scripts" tmux-wrapper spawn {step} {epic} {story_id} \
>   --agent "$agent" \
>   --command "$("$scripts" tmux-wrapper build-cmd {step} {story_id} --agent "$agent")")
> ```
> **Missing `--command` = session sits idle → `never_active` failure!**

**FOR EACH story in range:**

```bash
"$scripts" orchestrator-helper state-update "$state_file" \
  --set currentStory={story_id} --set currentStep=step-03-execute \
  --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "- **[$(date -u +%Y-%m-%dT%H:%M:%SZ)]** Starting story {story_id}" >> "$state_file"

# Mark the current story row in progress using the rendered table headers
"$scripts" orchestrator-helper state-progress "$state_file" \
  --story "{story_id}" \
  --set status=in-progress

policy_sequence=$("$scripts" orchestrator-helper policy-sequence --state-file "$state_file")
```

Display: "**Story {N}/{total}: {title}**"
Use compact operator output format for routine progress:
```text
[story {N}/{total}] {step} -> {state} (agent={agent}, retries={attempts})
```
After any session completes (create/dev/auto/review): `"$scripts" tmux-wrapper kill "$session"`

**MANDATORY log pre-filter (all sessions):** Before any deep parsing, pre-filter logs with a single grep/regex pass and pass only focused output forward.
```bash
log_file=$(echo "$result" | jq -r '.output_file')
log_focus=$(grep -nE "SUCCESS|FAIL|ERROR|CRITICAL|WARN|RETRY|ESCALATE" "$log_file" | head -n 120)
if [ -z "$log_focus" ]; then
  log_focus=$(tail -n 120 "$log_file")
fi
```
If multiple logs exist, run one grep/regex pass across all log files and forward only matched lines + file names.

**Compact result contract (required):**
- Return only: `next_action`, `confidence`, `error_class`, `retryable`, `reasons`, `session_id`
- Do not pass full raw logs to parent flow unless escalation explicitly requires evidence payload

### A. Create Story
*Skip if story file exists*

**Apply retry/fallback pattern from `{retryStrategy}`:** Up to 5 attempts, alternating agents, network-aware delays.

```bash
# Retry loop: see {retryStrategy}
# Resolve agent/model. Pass `--model` only when the current attempt is on
# the primary agent (model is bound to the primary). `"$primary_model"` is
# always quoted so bracketed IDs like `claude-opus-4-7[1m]` survive shell.
resolve_agent_for_task "create" "$state_file" "{story_id}"
if should_apply_primary_model "$current_agent"; then
  built_cmd=$("$scripts" tmux-wrapper build-cmd create {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
else
  built_cmd=$("$scripts" tmux-wrapper build-cmd create {story_id} --agent "$current_agent" --state-file "$state_file")
fi
session=$("$scripts" tmux-wrapper spawn create {epic} {story_id} \
  --agent "$current_agent" \
  --command "$built_cmd")
result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
"$scripts" tmux-wrapper kill "$session"
validation=$("$scripts" orchestrator-helper verify-step create {story_id} --state-file "$state_file")
```

- If `validation.verified == true`:
  ```bash
  # Update Story Progress: mark create-story done
  "$scripts" orchestrator-helper state-progress "$state_file" \
    --story "${story_id}" \
    --set create=done \
    --set status=in-progress
  ```
  → proceed to B
- If `validation.verified == false` AND attempts < 5 → retry with next agent (see `{retryStrategy}`)
- If `validation.verified == false` AND attempts == 5 → escalate (all retries exhausted)

### A.1 ATDD
*Run only if the pinned policy sequence includes `atdd`*

Use the same spawn/monitor/parse pattern as other session-exit steps:

```bash
if ! echo "$policy_sequence" | jq -e '.ok == true' >/dev/null; then
  echo "Pinned workflow sequence unavailable; cannot evaluate ATDD scope."
  exit 1
fi
if echo "$policy_sequence" | jq -e '.sequence | index("atdd")' >/dev/null; then
  "$scripts" orchestrator-helper state-update "$state_file" \
    --set currentStep=atdd \
    --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  resolve_agent_for_task "atdd" "$state_file" "{story_id}"
  if should_apply_primary_model "$current_agent"; then
    built_cmd=$("$scripts" tmux-wrapper build-cmd atdd {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
  else
    built_cmd=$("$scripts" tmux-wrapper build-cmd atdd {story_id} --agent "$current_agent" --state-file "$state_file")
  fi
  session=$("$scripts" tmux-wrapper spawn atdd {epic} {story_id} \
    --agent "$current_agent" \
    --command "$built_cmd")
  result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
  "$scripts" tmux-wrapper kill "$session"
  parsed=$("$scripts" orchestrator-helper parse-output "$(printf '%s' "$result" | jq -r '.output_file')" atdd --state-file "$state_file")
  next_action=$(echo "$parsed" | jq -r '.next_action')
else
  echo "[story {N}/{total}] atdd -> skipped (not in policy sequence)"
  next_action="proceed"
fi
```

- If `next_action == "proceed"`:
  ```bash
  "$scripts" orchestrator-helper state-progress "$state_file" \
    --story "${story_id}" \
    --set atdd=done \
    --set status=in-progress
  ```
  → continue to the next policy-defined step
- If `next_action == "retry"` or session crashed → retry with fallback pattern
- Treat successful completion as execution completion only; TEA artifact verification is not part of v1

When updating progress, do not assume the standard fixed column order if TEA mode is active.

### B. Dev Story
*Run only if the pinned policy sequence includes `dev`*

If `dev` is not present in the pinned sequence, skip this phase entirely and proceed directly to the review phase transition below.

**Apply retry/fallback pattern from `{retryStrategy}`:** Up to 5 attempts, alternating agents.

```bash
if ! echo "$policy_sequence" | jq -e '.ok == true' >/dev/null; then
  echo "Pinned workflow sequence unavailable; cannot evaluate Dev Story scope."
  exit 1
fi
dev_in_scope=false
if echo "$policy_sequence" | jq -e '.sequence | index("dev")' >/dev/null; then
  dev_in_scope=true
else
  echo "[story {N}/{total}] dev -> skipped (not in policy sequence)"
fi
if [ "$dev_in_scope" = "true" ]; then
  # Retry loop with agent alternation: see {retryStrategy}
  "$scripts" orchestrator-helper state-update "$state_file" \
    --set currentStep=dev \
    --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  resolve_agent_for_task "dev" "$state_file" "{story_id}"
  if should_apply_primary_model "$current_agent"; then
    built_cmd=$("$scripts" tmux-wrapper build-cmd dev {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
  else
    built_cmd=$("$scripts" tmux-wrapper build-cmd dev {story_id} --agent "$current_agent" --state-file "$state_file")
  fi
  session=$("$scripts" tmux-wrapper spawn dev {epic} {story_id} \
    --agent "$current_agent" \
    --command "$built_cmd")
  result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
  "$scripts" tmux-wrapper kill "$session"
fi
```

**Session Parsing Contract (required):**
- Preferred: use Session Output Parser prompt from `{subagentPrompts}` on `result.output_file`
- Fallback: use local parser below
- Return normalized schema only: `next_action`, `confidence`, `error_class`, `reasons`

```bash
if [ "$dev_in_scope" = "true" ]; then
  parsed=$("$scripts" orchestrator-helper parse-output "$(printf '%s' "$result" | jq -r '.output_file')" dev --state-file "$state_file")
  next_action=$(echo "$parsed" | jq -r '.next_action')
  confidence=$(echo "$parsed" | jq -r '.confidence // 0.0')
  error_class=$(echo "$parsed" | jq -r '.error_class // "none"')
  reasons=$(echo "$parsed" | jq -c '.reasons // []')
else
  next_action="proceed"
fi
```

- If `dev_in_scope == "false"` → skip directly to C (next step)
- If `dev_in_scope == "true"` and `next_action == "proceed"`:
  ```bash
  # Update Story Progress: mark dev-story done
  "$scripts" orchestrator-helper state-progress "$state_file" \
    --story "${story_id}" \
    --set dev=done \
    --set status=in-progress
  ```
  → proceed to C (next step)
- If `dev_in_scope == "true"` and (`next_action == "retry"` OR `result.final_state == "crashed"`):
  - Attempts < 5 → retry with next agent (see `{retryStrategy}`)
  - Plateau detected (same task 3x) → DEFER story, continue to next
  - Attempts == 5 → escalate (all retries exhausted)

## Auto-Proceed to Review Phase

Display: "**Dev story complete. Proceeding to the next policy-defined quality phase...**"

```bash
"$scripts" orchestrator-helper state-update "$state_file" \
  --set currentStep=step-03a-execute-review \
  --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "- **[$(date -u +%Y-%m-%dT%H:%M:%SZ)]** Dev complete, proceeding to review phase" >> "$state_file"
```

## Then
→ Immediately load and execute `{nextStep}`
