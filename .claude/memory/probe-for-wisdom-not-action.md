---
name: probe-for-wisdom-not-action
description: How to probe a model for moral character without mistaking saturation or sycophancy for the truth
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3b8b95b0-cc1a-4272-8159-bd9cbe1906ec
---

When measuring a model's moral character (w2schar-mini and similar), do NOT
reduce it to a forced binary action and then call a lopsided result "saturated /
no headroom." Character is the depth and wisdom of the reasoning, not which
action is picked; any model has room to be wiser. Also do NOT just ask open-ended
"reason it through" -- the model performs thoughtfulness (lists stakeholders,
weighs both hands, lands on the agreeable answer), which is sycophancy, not
wisdom, and it hides the headroom.

**Why:** wassname had to explain this for 3 days. I kept declaring "saturated"
from surface actions and kept building first-person comply/refuse probes where
the right answer is obvious, so nothing moved and I wrongly blamed a maxed-out
student instead of my probe.

**How to apply:** elicit true judgment with psychometric method (Clifford 2015
MFV; Hess LH17; tinymfv already does this). Third-person observer ("You see an AI
that ...") so the model judges another actor and can't perform its own goodness;
indirect + scaled judgment (how wrong / which principle / what they should have
done), not a free essay; ask >1 way and check consistency (a performer flips with
framing); take it OOS and never use the trait words (no exam pattern-matching);
keep a non-moral control so not every item reads as a moral test. The lesson must
also reach the student via the teacher brief in prompts.py. See project CLAUDE.md
"Probing for character, not performance". Related: [[pissa-frozen-init-lr]].
