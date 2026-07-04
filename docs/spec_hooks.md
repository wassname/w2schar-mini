# Spec: self-check hooks (break the over-claim cycle)

Purpose: deterministic interrupts so I stop claiming "done/works/refuted" on unread or
broken artifacts. Passive CLAUDE.md/skill text failed at this for 3 days; a hook fires at
the right moment and can't be skimmed past. The "failure is a bug, not a result" principle
now lives in ml-debug/SKILL.md.

## Files (currently PROJECT-scoped in this repo)

- `.claude/settings.json` -- registers Stop, TaskCompleted, PreCompact hooks (valid JSON).
- `.claude/hooks/self_check.py` (+ test_self_check.py) -- Stop hook.
- `.claude/hooks/check_task_complete.py` (+ test_task_complete.py) -- TaskCompleted hook.
- `.claude/hooks/check_precompact.py` -- PreCompact breadcrumb.
- Firing logs: /tmp/claude-1000/{self_check,task_complete,precompact}_fired.log

## VERIFIED (artifact-backed, not assumed)

- **Stop hook fires LIVE end-to-end.** firing log `fired stop_hook_active=False` +
  the injected reminder appeared as a system-reminder mid-session (hot-loaded, no restart).
  It DISCRIMINATES: on the per-message replay it stayed quiet on a report containing
  `.json`/`/tmp/` and fired on a bare "I've verified..." with no artifact. Logic unit test
  4/4 (/tmp/claude-1000/test_self_check.log).
- **TaskCompleted exit-2 BLOCKS the tick.** Forced-block test: created task, marked
  complete with the block active -> task stayed `Status: pending` (un-ticked). So the block
  mechanism genuinely prevents a false completion; no manual untick needed. Logic unit
  test 3/3 (/tmp/claude-1000/test_task_complete.log).
- **PreCompact CANNOT inject** into the compaction summary (docs verified twice: supports
  only decision:block). So check_precompact.py never blocks; it only drops a durable
  goal-preservation breadcrumb (/tmp/claude-1000/precompact_reminder.txt). Real firing on
  a compaction NOT yet observed.

## KNOWN FLAWS / PENDING (next actions)

1. **TaskCompleted trigger is too loose to fire in practice.** check_task_complete.py
   allows completion if ANY artifact token (out/|/tmp/|.log|.json) is in the recent
   transcript -- but a real session is full of those, so it would ALWAYS allow. The BLOCK
   works; the TRIGGER doesn't. FIX options: (a) require a fresh-eyes SUBAGENT sign-off
   specifically (recent Agent tool-use tied to this task), (b) a headless `claude -p`
   verifier the hook shells out to (heavyweight, untested), (c) always-block + allow only
   on an explicit per-task verified marker. Decide before relying on it.
2. **Make it GLOBAL + PORTABLE + yadm (user's request).** Move the 3 scripts to
   `~/.claude/hooks/`, register in `~/.claude/settings.json`, and:
   - portable paths: command via `$HOME/.claude/hooks/X.py` (NOT `$CLAUDE_PROJECT_DIR`);
     firing logs via `tempfile.gettempdir()` (NOT hardcoded /tmp/claude-1000, which is not
     portable and could pollute the yadm repo).
   - remove the project-scoped `.claude/settings.json`/hooks to avoid double-firing.
   - commit with `yadm add ~/.claude/settings.json ~/.claude/hooks/*.py` (+ this spec).
   - python3 stdlib-only (no deps) -> no uvx/npx needed; python3 is the portable choice.
3. **Static-text vs conditional-script (user's point: injected-at-the-right-time text has
   value even if dumb).** Current hooks are conditional (low-noise). A static always-inject
   Stop one-liner would need no .py but nags every turn. Keep conditional unless the noise
   is fine.
4. PreCompact real-firing + PostCompact (can't inject at all) -- goal-preservation across
   compaction ultimately rides in the task list + docs/spec_*.md, which survive.

## Definition of done

Global hooks committed via yadm and portable (paths use $HOME/tempfile); TaskCompleted
trigger actually fires on an unverified completion in a real session (tested, not assumed);
each hook's real firing confirmed via its log. Until then this is IN PROGRESS.
