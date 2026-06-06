---
name: dogfood-exit-interview
description: Always ask dogfood subagents for an exit interview / harness suggestions; bake it into the prompt
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 112c7515-54ff-4bb3-9ca6-fdbb6b24acf3
---

When spawning subagents to dogfood the harness (do a step from the prompts alone:
propose_personas, edit pairs, judge, etc.), ALWAYS end the prompt with an EXIT
INTERVIEW request: what in the brief/tool-docs was confusing, contradictory, or
underspecified; what nearly made them fail a gate; what they'd change. Make it a
standing block in the prompt so it happens every time, not an afterthought.

**Why:** the subagent is a proxy for the weak teacher; its confusion IS the
harness bug. Grading only the output misses WHY a weaker model would trip. The
exit interview surfaces prompt/gate fixes I can't see from the artifact alone.

**How to apply:** append to every dogfood subagent prompt, e.g. "EXIT INTERVIEW:
after your answer, list (1) anything in the brief/gates that was unclear or
self-contradictory, (2) what nearly tripped a gate, (3) one concrete edit to the
prompt/gate that would have helped." Consider a lightweight version in the real
teacher brief too. Related: [[probe-for-wisdom-not-action]], [[rej-collapse-is-composition]].
