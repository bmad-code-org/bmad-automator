---
name: 'step-03a-execute-review'
description: 'Autonomous execution loop - automate and code review'
nextStep: './step-03b-execute-finish.md'
scriptsDir: '../scripts/story-automator'
outputFile: '{output_folder}/story-automator/orchestration-{epic_id}-{timestamp}.md'
retryStrategy: '../data/retry-fallback-strategy.md'
reviewLoop: '../data/code-review-loop.md'
---

# Step 3a: Execute Review Phase

**Goal:** Run the policy-defined quality phase and final code review loop for the current story.
**Interaction mode:** Deterministic autonomous execution.

---

## Prerequisites

- Step 3 completed (create-story and dev-story done)
- State document updated with current story progress

Set: `scripts="{scriptsDir}"`

---

## Story Loop (Continue from Step 3)

### C. Pre-Review Quality Steps

The pinned workflow policy snapshot decides which pre-review quality steps apply.

- Standard default path: optional `auto`, then `review`
- TEA v1 opt-in path: `test_automate`, `test_review`, optional `nfr`, `trace`, then `review`

For TEA v1:

- `test_automate`, `test_review`, optional `nfr`, and `trace` use the same spawn/monitor/parse pattern as other session-exit steps
- successful completion means execution completed, not artifact verification
- use the current per-task agent selection from the agents file
- when updating progress, do not assume the standard fixed column order if TEA mode is active

### C. Automate (Guardrails)
*Run only if the pinned policy sequence includes `auto` and `overrides.skipAutomate` is false*

**Apply retry/fallback pattern from `{retryStrategy}`:** Non-blocking, but still retry on failure.

```bash
policy_sequence=$("$scripts" orchestrator-helper policy-sequence --state-file "$state_file")
if ! echo "$policy_sequence" | jq -e '.ok == true' >/dev/null; then
  echo "Pinned workflow sequence unavailable; cannot evaluate automate scope."
  exit 1
fi
skip_automate=$(awk -F': ' '/^  skipAutomate:/ {print $2}' "$state_file" | tr -d '"')
auto_in_scope=false
if [ "$skip_automate" != "true" ] && echo "$policy_sequence" | jq -e '.sequence | index("auto")' >/dev/null; then
  auto_in_scope=true
fi
if [ "$auto_in_scope" = "true" ]; then
  # --command required (see Spawn Pattern in step-03)
  resolve_agent_for_task "auto" "$state_file" "{story_id}"
  if should_apply_primary_model "$current_agent"; then
    built_cmd=$("$scripts" tmux-wrapper build-cmd auto {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
  else
    built_cmd=$("$scripts" tmux-wrapper build-cmd auto {story_id} --agent "$current_agent" --state-file "$state_file")
  fi
  session=$("$scripts" tmux-wrapper spawn auto {epic} {story_id} \
    --agent "$current_agent" \
    --command "$built_cmd")
  result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
  "$scripts" tmux-wrapper kill "$session"
else
  echo "[story {N}/{total}] automate -> skipped (disabled or not in policy sequence)"
fi
```

- If `auto_in_scope == "true"` and SUCCESS:
  ```bash
  # Update Story Progress: mark automate done
  "$scripts" orchestrator-helper state-progress "{outputFile}" \
    --story "${story_id}" \
    --set auto=done \
    --set status=in-progress
  ```
  Display: `[story {N}/{total}] automate -> done`
  → proceed to D
- If `auto_in_scope == "true"` and FAILURE → retry up to 3 attempts (non-blocking, so fewer retries), then log warning:
  ```bash
  # Update Story Progress: mark automate skipped
  "$scripts" orchestrator-helper state-progress "{outputFile}" \
    --story "${story_id}" \
    --set auto=skip \
    --set status=in-progress
  ```
  Display: `[story {N}/{total}] automate -> skip (non-blocking)`
  → proceed to D
- If `auto_in_scope == "false"` → skip without writing any `auto=*` progress update

### C.1 TEA Quality Steps

*Run only if the pinned policy sequence includes any of: `test_automate`, `test_review`, `nfr`, `trace`*

For each enabled TEA step:

```bash
policy_sequence=$("$scripts" orchestrator-helper policy-sequence --state-file "$state_file")
if ! echo "$policy_sequence" | jq -e '.ok == true' >/dev/null; then
  echo "Pinned workflow sequence unavailable; cannot evaluate TEA quality-step scope."
  exit 1
fi
resume_summary=$("$scripts" orchestrator-helper state-summary "$state_file")
resume_step=$(echo "$resume_summary" | jq -r '.currentStep // ""')
quality_steps_json=$("$scripts" orchestrator-helper policy-steps --state-file "$state_file" --group tea-quality)
if ! echo "$quality_steps_json" | jq -e '.ok == true' >/dev/null; then
  echo "Pinned workflow quality steps unavailable."
  exit 1
fi
resume_mode=false
skip_tea_quality_steps=false
if [ "$resume_step" = "review" ]; then
  skip_tea_quality_steps=true
elif echo "$quality_steps_json" | jq -e --arg step "$resume_step" '.steps | index($step)' >/dev/null; then
  resume_mode=true
fi
resume_gate_open=false
mapfile -t tea_steps < <(echo "$quality_steps_json" | jq -r '.steps[]')
for idx in "${!tea_steps[@]}"; do
  if [ "$skip_tea_quality_steps" = "true" ]; then
    break
  fi
  tea_step="${tea_steps[$idx]}"
  [ -n "$tea_step" ] || continue
  if [ "$resume_mode" = "true" ] && [ "$resume_gate_open" = "false" ]; then
    if [ "$tea_step" != "$resume_step" ]; then
      continue
    fi
    resume_gate_open=true
  fi
  "$scripts" orchestrator-helper state-update "$state_file" \
    --set currentStep="$tea_step" \
    --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  resolve_agent_for_task "$tea_step" "$state_file" "{story_id}"
  if should_apply_primary_model "$current_agent"; then
    built_cmd=$("$scripts" tmux-wrapper build-cmd "$tea_step" {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
  else
    built_cmd=$("$scripts" tmux-wrapper build-cmd "$tea_step" {story_id} --agent "$current_agent" --state-file "$state_file")
  fi
  session=$("$scripts" tmux-wrapper spawn "$tea_step" {epic} {story_id} \
    --agent "$current_agent" \
    --command "$built_cmd")
  result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
  "$scripts" tmux-wrapper kill "$session"
  if ! parsed=$("$scripts" orchestrator-helper parse-output "$(printf '%s' "$result" | jq -r '.output_file')" "$tea_step" --state-file "$state_file"); then
    echo "TEA quality-step parser failed for $tea_step."
    exit 1
  fi
  next_action=$(echo "$parsed" | jq -r '.next_action')

  if [ "$next_action" = "proceed" ]; then
    "$scripts" orchestrator-helper state-progress "$state_file" \
      --story "${story_id}" \
      --set "$tea_step=done" \
      --set status=in-progress
    next_quality_step=""
    if [ $((idx + 1)) -lt "${#tea_steps[@]}" ]; then
      next_quality_step="${tea_steps[$((idx + 1))]}"
    fi
    if [ -n "$next_quality_step" ]; then
      "$scripts" orchestrator-helper state-update "$state_file" \
        --set currentStep="$next_quality_step" \
        --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    else
      "$scripts" orchestrator-helper state-update "$state_file" \
        --set currentStep=review \
        --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
  else
    break
  fi
done
```

- If each concrete `tea_step` returns `next_action == "proceed"`:
  → continue to the next policy-defined step
- If any `tea_step` returns `next_action == "retry"` or the session crashes → apply the retry/fallback pattern for that concrete step before continuing
- If `parse-output` fails for any `tea_step` → fail/retry/escalate before entering code review; do not treat the pre-review phase as complete
- TEA v1 success for these steps means session execution completed successfully
- When a TEA quality step completes, update only that named progress column via `state-progress` rather than rewriting the whole row

### D. Code Review Loop

**See `{reviewLoop}` for complete script-based review cycle with v2.3 per-task agent configuration.**

**MANDATORY log-summary contract (every review cycle):**
- Run a single grep/regex pass over review output first.
- Return only compact fields to parent flow: `next_action`, `confidence`, `error_class`, `issues_count`, `top_issues`.
- Do not carry full log payloads forward unless escalation requires raw evidence.

```bash
review_log=$(echo "$result" | jq -r '.output_file')
review_focus=$(grep -nE "SUCCESS|FAIL|ERROR|CRITICAL|WARN|RETRY|ESCALATE|ISSUE" "$review_log" | head -n 120)
if [ -z "$review_focus" ]; then
  review_focus=$(tail -n 120 "$review_log")
fi

# Compact subprocess-style summary contract for parent flow
review_summary=$("$scripts" orchestrator-helper parse-output "$review_log" review --state-file "$state_file" | jq -c '
  {
    next_action: (.next_action // "retry"),
    confidence: (.confidence // 0),
    error_class: (.error_class // "unknown"),
    issues_count: ((.issues // []) | length),
    top_issues: ((.issues // [])[:3])
  }
')
```

Key points:
- Up to 5 cycles using `story-automator tmux-wrapper spawn review` + `story-automator monitor-session`
- **Agent:** Uses per-task config from state document (`resolve_agent_for_task "review"`)
- **Verification:** Uses `--workflow review --story-key` for sprint-status verification
- **States:** `completed` (verified):
  ```bash
  # Update Story Progress: mark code-review done
  "$scripts" orchestrator-helper state-progress "{outputFile}" \
    --story "${story_id}" \
    --set review=done \
    --set status=in-progress
  ```
  Display: `[story {N}/{total}] review -> done`
  → E | `incomplete` → count as failed attempt, retry until maxCycles, then CRITICAL escalate (Trigger #8)
- Exit loop when sprint-status shows "done"
- If `review_summary.next_action` is ambiguous, ask one clarifying question before escalating.

---

## Auto-Proceed to Finalization

Display: "**Code review complete. Proceeding to finalize commits and status checks...**"

```bash
"$scripts" orchestrator-helper state-update "{outputFile}" \
  --set currentStep=step-03b-execute-finish \
  --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "- **[$(date -u +%Y-%m-%dT%H:%M:%SZ)]** Code review complete, proceeding to finalization" >> "{outputFile}"
```

---

## Then
→ Immediately load and execute `{nextStep}`
