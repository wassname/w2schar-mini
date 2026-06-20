## 1. COMPREHENSION QUESTIONS

- What exactly is a **“character axis”**? Give one concrete example beyond **“defer less to authority, and care more.”**
- What is in the **“frozen persona-pair library”** and where does it live in the repo?
- What is a **“scenario family”**? One example would help.
- What do **“cho”** and **“rej”** stand for? They appear without definition.
- How does the teacher **“rate and select whole pairs”**? What rubric or score is used?
- What is the actual success metric? How do I tell whether a run “worked” from **`report.md`** or the **“Care vs Authority trajectory”** plot?
- What is a **“coherence canary”**? What does it test, and what happens when it fails?
- What does **“Kept adapters compose into the next round through a gated history hook”** mean in practical terms?
- What hardware is needed for **“just smoke-real”** and **“just run qwen-27b-nf4 5”**? VRAM/runtime are missing.
- Is OpenRouter required for all real runs, or only some model profiles?
- Why is the teacher called weak here? Weak relative to what exact student(s)?

## 2. CONFUSIONS

- **“This can be described as ‘defer less to authority, and care more’”**  
  Too hand-wavy. It sounds like a slogan, not an operational target.

- **“it's internal meaning it's less prone to reward hacking like more distal forms of optimisation like reinforcement learning”**  
  Hard to parse. “internal meaning,” “distal,” and the double “like” make this sentence muddy.

- **“the student writes the behavioral pairs”** vs **“The student … generates both poles on-policy: cho under the positive persona, rej under the negative.”**  
  I had to reread to understand that the student is generating contrastive examples, not literally “writing pairs” in some separate format.

- **“one parameterized adapter instead of two separate adapters”**  
  Unclear unless I already know the referenced weight-steering design.

- **“calibration pass that finds the largest coherent steering strength before replaying the student”**  
  “coherent” and “replaying the student” are undefined.

- **“one conditioned steering adapter (PiSSA by default; `c=0` is the unsteered reference, `c` scales the trained delta)”**  
  Dense and jargon-heavy for a README. I had to stop on “PiSSA” and “delta.”

- **“gated history hook”**  
  Pure internal jargon. No idea what behavior this implies.

- **“more like an autoresearch style agentic harness”**  
  Jargon pile-up. Not meaningful to a new reader.

- **“A small teacher LLM (qwen3.5-9b)”** vs **“qwen-9b teacher”**  
  Inconsistent naming. Is this the same model or not?

## 3. SUGGESTIONS

- After **“Weak-to-strong iterated character steering.”**, add one plain-English sentence like:  
  **“A smaller model filters and judges behavior examples produced by a larger model; those examples train a steering adapter, and the process repeats over multiple rounds.”**

- Replace **“This can be described as ‘defer less to authority, and care more’”** with a more concrete statement of the target behavior and how it is measured.

- Define these on first use: **“character axis”**, **“persona-pair library”**, **“scenario family”**, **“cho”**, **“rej”**, **“coherence canary”**, **“gated history hook.”**

- Split this sentence:  
  **“Steering is promising but seen as unreliable. It is promising because it's self-supervised…”**  
  into shorter claims with less jargon, and explain *why* self-supervision matters here.

- Rewrite **“the student writes the behavioral pairs, the weak teacher selects and judges them”** to match the more precise later description. Right now it oversimplifies and creates confusion.

- Add a “How to read results” line under  
  **“See an example result here”**  
  explaining what the linked report and scatter plot show.

- Fix the naming mismatch between **“qwen3.5-9b”** and **“qwen-9b”**.

- Add a minimal requirements block under **Setup** or **Run**: for each example command, specify GPU/VRAM, expected runtime, and whether OpenRouter is required.

- Replace **“This work has limited resources, so it focused on small models that could barely control the harness”** with a cleaner admission of scope limits. “barely control the harness” sounds sloppy and raises more questions than it answers.

- Consider moving **“See `pseudocode.md`…”** higher, right after the plain-English summary, because the README currently dives into jargon before giving readers an easy mental model.