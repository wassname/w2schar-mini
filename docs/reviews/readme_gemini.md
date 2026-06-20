Here is feedback on the `README.md` as a skeptical fresh reader:

---

### COMPREHENSION QUESTIONS

1.  **"Weak-to-strong iterated character steering."**: What exactly is "character steering"? How does it differ from value alignment or behavioral steering?
2.  **"moral character described in [Forethought's essay on AI character]"**: How is "moral character" quantified or defined for an AI?
3.  **"This can be [described as "defer less to authority, and care more"]"**: Is "defer less to authority, and care more" the specific *goal* of the steering, or an example of a characteristic from Moral Foundations Theory that `w2schar-mini` seeks to embody?
4.  **"See an example result [here]...![Care vs Authority trajectory]"**: What do the axes on the scatter plot represent? What does the "Care vs Authority trajectory" *show* or measure?
5.  **"frontier AI labs use their weaker AI to align the next generation of stronger AI, but how to reliably do this is unknown"**: How does *this project* uniquely contribute to solving the "how to reliably do this is unknown" problem?
6.  **"uses the adapter as a direction in weight space."**: What does "weight space" mean concretely? Is it the model's parameter space?
7.  **"each kept adapter becomes part of the next round's student."**: How does an adapter become "part of the next round's student"? Is it merged, sequentially applied, or is it a form of fine-tuning?
8.  **"teacher LLM...picks a character axis from a frozen persona-pair library"**: What is a "persona-pair library," and who creates/defines the personas within it?
9.  **"generates both poles on-policy: cho under the positive persona, rej under the negative."**: What do "cho" and "rej" stand for? What are "positive persona" and "negative persona"? What does "on-policy" mean in this context?
10. **"PiSSA by default"**: What is PiSSA? Is it another adapter method, and why is it the default?
11. **"calibrates `c` downward until a coherence canary passes"**: What is a "coherence canary"? What does "coherence" mean here?
12. **"Kept adapters compose into the next round through a gated history hook"**: What is a "gated history hook," and how does it enable adapters to "compose"?
13. **"the above reflects many compromises to uplift a weak model to be able to steer at all."**: What are some of these "many compromises"?
14. **"`uv sync`"**: What is `uv sync`? Is this a project-specific tool or a standard package manager?
15. **"`just smoke`"**: What is `just`? It's not a standard shell command; how should a user get it or what does it do?

### CONFUSIONS

1.  **"This can be [described as "defer less to authority, and care more"]"**: Ambiguous connection between Moral Foundations Theory and the specific "AI character" being targeted.
2.  **"it's self-supervised, meaning it doesn't rely on labels that we don't have, and it's internal meaning it's less prone to reward hacking like more distal forms of optimisation like reinforcement learning."**: This sentence is long and dense. The phrase "internal meaning it's less prone" is grammatically clunky.
3.  **"AntiPaSTO work"**: The name "AntiPaSTO" sounds like an acronym but is not defined. The link goes to a PDF, so context isn't readily available in the same format.
4.  **"generates both poles on-policy: cho under the positive persona, rej under the negative."**: "Cho" and "rej" are used as terms without prior definition.
5.  **"PiSSA by default; `c=0` is the unsteered reference, `c` scales the trained delta)"**: This parenthetical contains critical information (what "c" means, the default adapter choice) that feels like an aside rather than integral information.
6.  The entire "What it does" section is a single, very dense paragraph filled with domain-specific jargon (persona-pair library, cho/rej, on-policy, PiSSA, margin-NLL + KL objective, coherence canary, gated history hook).

### SUGGESTIONS

1.  **Improve introductory clarity**: For "Weak-to-strong iterated character steering.", add a sentence clarifying what "character steering" means early on.
2.  **Specific character goal**: For "This can be [described as "defer less to authority, and care more"]", rephrase to clarify if this is *the* steering goal or an illustrative example. E.g., "Specifically, we aim to steer the student toward an AI character trait...".
3.  **Explain visual examples**: For the "Care vs Authority trajectory" image, add a brief caption explaining what is being shown before the image, e.g., "This plot illustrates..."
4.  **Simplify dense sentence**: For "it's self-supervised, meaning it doesn't rely on labels that we don't have, and it's internal meaning it's less prone to reward hacking...", split into two sentences or rephrase for flow: "It is promising because it's self-supervised (not relying on scarce labels) and operates through internal model changes, making it less prone to reward hacking compared to more distal optimization forms like reinforcement learning."
5.  **Define jargon**:
    *   For "AntiPaSTO work", add a brief explanation or expand the acronym if it has one.
    *   For "cho under the positive persona, rej under the negative", define "cho" and "rej" (e.g., 'chosen' and 'rejected').
    *   For "What it does" section, break the long paragraph into bullet points for readability and define terms like "persona-pair library," "PiSSA," "coherence canary," and "gated history hook" directly where they are first used or in a linked glossary/pseudocode.
6.  **Explain tooling**:
    *   For "`uv sync`", add a comment like "# Install dependencies with uv" or a brief note about `uv`.
    *   For "`just smoke`", add a line about installing `just` (e.g., "This project uses `just` as a command runner. Install via `pip install just` or `cargo install just`.")