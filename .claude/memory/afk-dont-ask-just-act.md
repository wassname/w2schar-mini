---
name: afk-dont-ask-just-act
description: "When wassname is AFK, do NOT stop to ask for design decisions — pick the best option, execute, gym/smoke-test, commit, keep GPU busy toward the goal"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 112c7515-54ff-4bb3-9ca6-fdbb6b24acf3
---

When wassname says he is AFK (or invokes the afk skill), do NOT pause to ask him
to choose between options or approve a design call — asking when he is asleep
wastes wall-clock and money and leaves the GPU idle. Make the call yourself with
research taste, execute it fully, verify (gym/smoke/subagent), commit, and chain
to the next step.

**Why:** wassname: "please don't stop to ask me you cost me money. I'll be afk ...
I need to sleep and do meat things." Earlier: "don't await my call, I'm afk ok
just be clear on the goal." He trusts autonomous judgment and wants proof-of-
progress when he returns, not a question queue.

**How to apply:** state the goal + your chosen option in the journal, then DO it.
Reserve the audit-run "stop and confirm before KILL+FIX" rule for when he is
ACTIVE; when AFK, kill wasteful jobs and requeue with a hypothesis label per the
afk skill. Still leave GPU idle over a *predetermined null* (that is a research
call, not a question) — but if you have a grounded fix, run it, don't wait. Only
surface a decision if it is truly irreversible AND high-stakes AND you cannot
form a confident lean. Related: [[guide-dont-prescribe]], [[attractor-is-seat-driven]].
