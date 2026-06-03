---
name: prefer-in-repo-docs
description: "Persist durable knowledge in-repo (docs/AGENTS.md/justfile/README), not Claude-only memory"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3b8b95b0-cc1a-4272-8159-bd9cbe1906ec
---

User often runs non-Claude agents that have no memory store. So durable
findings, conventions, and entrypoints must live IN the repo where any agent or
human sees them: `RESEARCH_JOURNAL.md`, `AGENTS.md`/`CLAUDE.md`, the `justfile`,
`README`, or `docs/`.

**Why:** Claude memory is invisible to other runtimes and to a human skimming
the repo; it silently rots out of band.

**How to apply:** When you find something worth keeping (root cause, working
profile, gotcha), write it as a journal entry, a justfile recipe, or a doc line,
and make the entrypoint obvious like a normal repo. Use Claude memory only for
cross-session working preferences like this one, not for project facts that
belong in the repo. See [[pissa-frozen-init-lr]] (that finding lives in
RESEARCH_JOURNAL.md entry (b); the memory file is a redundant pointer).
