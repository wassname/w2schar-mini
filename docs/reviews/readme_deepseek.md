## 1. COMPREHENSION QUESTIONS

- **What is a "frozen persona-pair library"?** This term is introduced with no definition, no link, and no example. The entire mechanism hinges on it but it's a black box.

- **What does "cho" and "rej" mean?** These appear in "cho under the positive persona, rej under the negative" — are they abbreviations? Acronyms? Arbitrary variable names? Never defined.

- **What actually ships or runs?** Is this a CLI tool? A Python library? A research notebook? The "Run" section has `just` commands but never states what language, framework, or entry point this is.

- **"Kept adapters compose into the next round through a gated history hook"** — what is a "gated history hook"? Is this a known ML concept or a custom term? Completely opaque.

- **"coherence canary passes"** — what is a coherence canary? What condition constitutes passing vs. failing? Never explained.

- **What is the actual output?** The link to `report.md` and a scatter plot are given as an "example result," but what does a user get when they run this? A file? A score? A model? Unclear.

- **"c=0 is the unsteered reference, c scales the trained delta"** — what is `c`? A hyperparameter? A coefficient? How does a user set or interpret it?

- **"one parameterized adapter instead of two separate adapters"** — what were the original two adapters? What does this change mean? Only decipherable if you've already read the weight-steering and AntiPaSTO papers.

---

## 2. CONFUSIONS

- **"We ask a weak teacher model to steer a stronger student model toward the moral character described in [Forethought's essay]"** — "steer toward the moral character" is vague. Does it mean the student outputs text that reflects those values? Refuses harmful requests? Changes its persona? The action is underspecified.

- **"defer less to authority, and care more"** — this is linked to Wikipedia's Moral Foundations Theory page as if it's an obvious summary, but MFT has five or six foundations. Which axis is "care more" vs. "defer less"? Authority is one foundation; care/harm is another. The mapping is hand-waved.

- **"the personas are stripped"** — the personas were just introduced as the mechanism for generating pairs. Now they're removed before training? Why? What remains? This reversal is jarring.

- **"margin-NLL + KL objective"** — two loss functions combined with no explanation of the margin, the weighting, or what the KL term operates on.

- **"replaying the student"** — replaying what? Completions from a saved snapshot? Regenerating? Unclear usage.

- **"The harness tries to empower the weak teacher by giving it the easier parts of the job."** — this sounds like an admission of weakness, but it's unclear which parts are "easier" and whether the division actually works. The sentence that follows (teacher selects axis, rates pairs, judges pre/post) doesn't clarify why those are easier than what the student does.

- **"This work has limited resources… the above reflects many compromises to uplift a weak model to be able to steer at all."** — this is unusually candid but leaves the reader uncertain: are these compromises documented? Are there known failure modes the reader should expect? Is the approach even valid or just interesting despite flaws?

---

## 3. SUGGESTIONS

- **Add a one-sentence concrete output description at the top.** Before "Why this is interesting," add something like: "Given a strong LLM you want to steer and a weaker LLM to act as judge, this tool produces a series of weight-space adapters that shift the strong model's behavior along a chosen moral axis, outputting a report and a trained adapter file."

- **Define cho/rej on first use.** Change "cho under the positive persona, rej under the negative" to "chosen (cho) under the positive persona, rejected (rej) under the negative" — assuming that's what they mean.

- **Explain the persona-pair library.** Add a sentence: "The persona-pair library is a static set of ~N contrasting character descriptions (e.g., 'You are compassionate' vs. 'You are callous') pre-written for each moral axis." And link to the actual file in the repo if it exists.

- **Define "coherence canary"** or drop the term. Either explain it ("a held-out prompt where the model must maintain coherent, non-degenerate outputs at the calibrated strength") or replace with plain language.

- **"gated history hook"** is jargon — "a hook that gates which past adapters are active" adds no clarity. Replace with: "previous adapters are composed via a weighted sum controlled by a learned gate" or just "previous adapters are cumulatively applied."

- **Move the "limited resources" caveat.** It currently reads as a pre-emptive excuse buried in the What it does section. Move it to a Limitations section at the end, or turn it into concrete guidance: "These design choices were made for weak teacher models. With stronger teachers, you could simplify by removing X and Y."

- **The "Why this is interesting" section has three sub-concepts (weak-to-strong, weight steering, the specific adapter variant) but no clear through-line.** Add a single sentence connecting them: "We combine weak-to-strong evaluation with iterative weight steering to test whether a weak judge can guide a strong model's character over multiple rounds."