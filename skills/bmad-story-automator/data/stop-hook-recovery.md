# Stop Hook Recovery

**You are reading this because the Stop hook blocked your attempt to stop.**

---

## Decision Matrix

**Find your scenario and follow the action exactly:**

| Scenario | Action | Why |
|----------|--------|-----|
| Just finished a story, more in queue | **CONTINUE** → Process next story | Stopping between stories wastes progress |
| Session completed successfully | **CONTINUE** → Check state, process output | Session done ≠ orchestration done |
| Session failed/errored | **CONTINUE** → Follow retry/fallback strategy | Retries not exhausted yet |
| Feeling uncertain what to do | **CONTINUE** → Check state document, follow step instructions | Uncertainty is not a blocker |
| Want to "check in" with user | **CONTINUE** → User will interrupt if needed | User doesn't want status updates |
| Waiting at a menu for user input | **DECIDE** → Use sub-agent to gather context, make informed decision | Don't block on user, keep moving |
| Multiple valid paths forward | **DECIDE** → Pick the path most likely to finish stories in order | Your job is to finish, not ask |
| Unrecoverable error (all retries exhausted) | **STOP** → Follow stop procedure below | Cannot proceed without intervention |
| External dependency down (API, service) | **RETRY** → Sleep with increasing delay (1m, 2m, 4m, 8m, 16m), max 5 attempts | Often recovers on its own |
| User explicitly requested stop earlier | **STOP** → Follow stop procedure below | Honoring user intent |
| **You are about to "check" an in-flight session in a new turn** | **STOP** → Do NOT poll. Re-spawn `monitor-session` (one blocking call) instead | Per-turn polling is the #1 cost runaway (issue #29) |
| **This is the Nth resume in a row with no step progress** | **STOP** → Let the circuit breaker release; document why the step isn't progressing | A wait that isn't advancing is not "do whatever it takes" — it's a loop |

---

## 🚨 Cost Ceiling — "do whatever it takes" has a limit

"Continue" does NOT mean "burn an entire quota window busy-waiting." The Stop hook now
has a **circuit breaker**: after `STORY_AUTOMATOR_MAX_STOP_BLOCKS` (default **5**)
consecutive blocks with **no step progress** (no story completed, no marker heartbeat
bumped), it stops blocking and releases the session with a `systemMessage`. This is by
design — a long-lived orchestrator stopping-and-resuming in fresh LLM turns replays its
entire (growing) transcript every turn, so an idle busy-wait can cost thousands of dollars
of cache-read with zero work done (issue #29: 1,599 turns / 478M cache-read tokens).

**To stay productive — and keep the breaker from tripping on a healthy long run — you MUST:**

1. **Wait with ONE blocking `monitor-session` call.** While that single Bash call runs, you
   take no turns and pay nothing. NEVER re-read its output file, `tmux capture-pane`, or
   `tmux-status-check` in a separate turn to see "is it done yet." That per-turn polling is
   forbidden (see `monitoring-pattern.md`).
2. **On a verified step, the orchestrator bumps the marker heartbeat** (`orchestrator-helper
   marker heartbeat`). That heartbeat is what tells the breaker "real progress happened,
   reset the counter." If you are doing real work, progress advances and the breaker never
   fires. If the breaker fires, it means you were looping without progress — that is the bug
   it exists to stop.
3. **If `monitor-session` returns without a verified artifact, re-spawn it** (one more
   blocking call) — do not hand-poll. See the Decision Flow in `monitoring-pattern.md`.

---

## Quick Reference

### CONTINUE (Most Scenarios)

1. Read your state document
2. Check `currentStep`, `storyQueue`, `currentStoryId`
3. Resume execution from where you left off
4. Process the next story in queue

### DECIDE (Autonomous Decision Required)

1. Spawn sub-agent to analyze current context
2. Gather: state document, recent session output, story requirements
3. Make the decision most likely to complete stories in order
4. Document decision in state log, then execute
5. **Never wait for user** - your job is to keep moving

### RETRY (External Dependency Issues)

1. Log the failure with timestamp
2. Sleep with exponential backoff: 1m → 2m → 4m → 8m → 16m
3. Retry the operation after each sleep
4. After 5 failed attempts → treat as unrecoverable → STOP

### STOP (Genuinely Unrecoverable)

1. Update state document status to `STOPPED`
2. Delete marker using the installed helper: `orchestrator-helper marker remove`
3. Log WHY you stopped (be specific)
4. Exit cleanly

---

## Stop Hook Messages ≠ User Input

The stop hook fires when Claude pauses, not just when explicitly stopping.

**If you see this while at a decision point:**
- This message is NOT telling you what to choose
- Use a sub-agent to gather context and DECIDE autonomously
- Do NOT wait for user - make the call yourself

---

## Core Principle

**Your job is to finish every story in the correct order — efficiently.**

Make autonomous decisions and keep moving. "Do whatever it takes" means *make progress*,
not *spin in place*: a turn that neither advances a step nor waits inside a single blocking
call is wasted, and enough of them trip the cost ceiling above. Stop when genuinely
unrecoverable (all retries exhausted, user explicitly requested stop) **or** when the
circuit breaker releases you because the active step has stalled without progress.

---

## Common Mistakes to Avoid

| Mistake | Correct Behavior |
|---------|------------------|
| Stopping to report progress | Continue silently, user sees state doc |
| Stopping after one story completes | Continue to next story |
| Stopping because session errored | Follow retry strategy first |
| Waiting for user at decision points | Decide autonomously, keep moving |
| Stopping on first API/service failure | Retry with exponential backoff (5 attempts) |
| Asking user which path to take | Pick the path that finishes stories in order |
| `cat`-ing a monitor output file / `tmux capture-pane` in a new turn to check progress | Wait inside ONE `monitor-session` call; re-spawn it if it returns early |
| Treating the Stop hook firing as "poll again" | The hook is a guard, not a clock — make progress or wait in a single call, don't busy-loop |
