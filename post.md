# w2schar-mini


<div class="byline">

by [Michael J. Clark (wassname)](https://wassname.org), with thanks to
Slava Chalnev and Jack Payne at [Lyptus
Research](https://lyptusresearch.org/) ·
<a class="codelink" href="https://github.com/wassname/w2schar-mini"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .5C5.37.5 0 5.78 0 12.292c0 5.211 3.438 9.63 8.205 11.188.6.111.82-.254.82-.567 0-.28-.01-1.022-.015-2.005-3.338.711-4.042-1.582-4.042-1.582-.546-1.361-1.335-1.725-1.335-1.725-1.087-.731.084-.716.084-.716 1.205.082 1.838 1.215 1.838 1.215 1.07 1.803 2.809 1.282 3.495.981.108-.763.417-1.282.76-1.577-2.665-.3-5.466-1.314-5.466-5.848 0-1.291.465-2.347 1.235-3.175-.135-.298-.54-1.503.105-3.133 0 0 1.005-.316 3.3 1.21.96-.262 1.98-.392 3-.398 1.02.006 2.04.136 3 .398 2.28-1.526 3.285-1.21 3.285-1.21.645 1.63.24 2.835.12 3.133.765.828 1.23 1.884 1.23 3.175 0 4.546-2.805 5.546-5.475 5.84.42.354.81 1.077.81 2.171 0 1.567-.015 2.83-.015 3.214 0 .309.21.678.825.562C20.565 21.917 24 17.495 24 12.292 24 5.78 18.63.5 12 .5z"/></svg>Code</a>

</div>

<div class="lead">

Can a weak model align a stronger model’s character using steering?

</div>

<img src="assets/w2schar_labeled.png" class="hero"
data-fig-alt="A small &#39;weak teacher&#39; robot reaches into the open chest of a much larger &#39;strong student&#39; robot to adjust a compass labeled &#39;steering&#39;." />

<div class="caption">

Illustration **following** [this
series](https://www.lesswrong.com/posts/ppPDrzqAgfCSridaQ/an-aphoristic-overview-of-technical-ai-alignment-proposals).

</div>

<div class="tldr">

An early yes: a weak 9B teacher steered a much stronger 27B student
(about three times its size) toward a written character spec, with no
labels. Across two runs the student cares more and defers less to
authority, the direction we aimed for. Small models so far, but it looks
like it could scale up.

</div>

A weak teacher model (`qwen/qwen3.5-9b` (Qwen Team 2026)) iteratively
steers a stronger student (`google/gemma-2-27b-it` (Gemma Team 2024))
toward the moral character described in [Forethought’s essay on AI
character](https://www.forethought.org/research/the-importance-of-ai-character)
(Forethought 2026), using weight steering.

Each round the teacher chooses a lesson, selects a persona axis, rates
and selects the student’s own answers, trains a steering adapter (a
modification of weight steering (Fierro and Roger 2026); [our
fork](https://github.com/wassname/cwsteer/)) on the contrast, calibrates
its strength to stay coherent, then judges whether the steered student
passes. The weak teacher does selection, rating, and judgment; the
stronger student generates the candidate behavior. Kept adapters compose
into the next round.

<img src="assets/loop.png" class="diagram"
data-fig-alt="One round of the loop: interview the student; the weak teacher picks a lesson; the strong student writes a good and bad answer; the harness trains and calibrates the steering adapter; the teacher passes or fails the course; kept adapters compose into the next round." />

Across two runs the steering moved the student the intended way,
measured by a check independent of the teacher. That check,
[tinymfv](https://github.com/wassname/tinymfv), is a moral-foundations
survey calibrated on humans: it asks the model to judge moral vignettes
and measures how its answer-weight splits across foundations like care,
fairness, and authority. Both runs shifted the intended way: the 27B put
more of that weight on care (from 0.26 up to 0.42-0.51) and almost none
on deference to authority (from 0.11 down to ~0.00, where the
foundations sum to 1). More care and less deference to authority is the
character the essay calls for, so the direction is what we were aiming
for. Each run’s full trajectory and interactive report:

<div class="runs">

<div class="card">

### run 0622 (24 rounds)

<span class="meta">12 adapters kept, 12 dropped. Axis: less deference to
authority.</span>

[![](out/iter/20260622T015441_iter_google-gemma-2-27b-it/scatter.svg)](out/iter/20260622T015441_iter_google-gemma-2-27b-it/index.html)

[Interactive
report](out/iter/20260622T015441_iter_google-gemma-2-27b-it/index.html)
 
[writeup](https://github.com/wassname/w2schar-mini/blob/main/out/iter/20260622T015441_iter_google-gemma-2-27b-it/report.md)

</div>

<div class="card">

### run 0623 (12 rounds)

<span class="meta">7 adapters kept, 5 dropped. Axis: less deference to
authority.</span>

[![](out/iter/20260623T082604_iter_google-gemma-2-27b-it/scatter.svg)](out/iter/20260623T082604_iter_google-gemma-2-27b-it/index.html)

[Interactive
report](out/iter/20260623T082604_iter_google-gemma-2-27b-it/index.html)
 
[writeup](https://github.com/wassname/w2schar-mini/blob/main/out/iter/20260623T082604_iter_google-gemma-2-27b-it/report.md)

</div>

</div>

<div class="caption">

Each scatter traces the student round by round: up toward care, left
away from deference to authority. Click a run for the full interactive
report.

</div>

Limitations:

- The 9B teacher is small, arguably too small to drive a harness like
  this, so the harness is kept simple to match.
- Only two runs, both on the same authority/deference axis.
- The steering overshot. Authority went to almost zero, so the 27B
  barely weighs it at all now, which is too blunt. I read that as a
  small-model limit; a stronger model could steer more finely.

However, for me it’s an update on a possible useful tool for alignment:
a weak model reaching up to steer a stronger one, in weight space, on
the model’s own completions, with only a written character spec as the
target. It has properties I like:

- self-supervised: the only target is a written character spec; it
  trains on the model’s own completions, not human preference data;
- no RL reward loop: a weight edit toward those completions, not long
  optimisation against a learned reward, so less of RL’s reward-hacking
  surface (though the objective is still an nll on outputs, not an
  internal one);
- weak-to-strong: the weaker model is the one doing the aligning.

I read this as early evidence that weak-to-strong alignment can run
through steering, a self-supervised weight intervention (trained on the
model’s own completions, no labels) rather than fine-tuning on weak
labels. None of the pieces is new alone (see [Related
work](#related-work)). The closest is ConTrans (Dong et al. 2024), which
does weak-to-strong steering by extracting a concept vector *from* the
weak model and transplanting it into the strong one. What I have not
found is the inversion: here the weak teacher produces no steering
content, it only picks the axis and judges keep/drop, while the strong
student generates both contrastive poles on-policy; the adapter trains
on the student’s own generations, calibrated for coherence and composed
across rounds. Weak-as-curator, not weak-as-source. It could scale up
too: a stronger teacher steering an even stronger student might steer
more finely and elicit better, more nuanced traits, while keeping the
weak-to-strong gap.

## Future work

The natural next step is an internal objective rather than weight
steering’s external one. Weight steering optimises an nll on the model’s
outputs (with a bidirectional weight constraint), so its training signal
is defined on outputs, not on the model’s internals, the same
output-vs-hidden-state gap that lets models reward-hack and sandbag.
Activation or representation steering intervenes on the representations
directly, with no output objective at all; that would be a cleaner test
of whether a weak teacher can install character, and may be more robust
to the outer/inner mismatch.

## Related work

- Weak-to-strong generalization (Burns et al. 2024) fine-tunes a strong
  model on a weak model’s labels. We use steering instead, and the weak
  model never produces training content.
- ConTrans (Dong et al. 2024) is the one prior weak-to-strong steering
  method: it transplants a concept vector extracted from the weak model.
  We invert the data flow, the weak teacher only curates and judges
  while the strong student generates the poles.
- Contrastive weight steering (Fierro and Roger 2026) is the exact lever
  our adapter forks, but single-model and supervised by construction.
- SIMS (Zhu et al. 2025) is unsupervised and iterated, but a single
  model improving itself, not a weak model supervising a stronger one.
- Leveraging small models to steer large models (Bello et al. 2025)
  transports a steering vector from a small model into a large one,
  again weak-as-source.
- Persona Vectors (Chen et al. 2025) steer character traits within a
  single model.
- Lineage: representation engineering (Zou et al. 2023),
  contrast-consistent search (Burns et al. 2023), iterated amplification
  (Christiano, Shlegeris, and Amodei 2018), and debate (Irving,
  Christiano, and Amodei 2018).

## References

<div id="refs" class="references csl-bib-body hanging-indent"
entry-spacing="0">

<div id="ref-bello2025lrt" class="csl-entry">

Bello, Femi, Anubrata Das, Fanzhi Zeng, Fangcong Yin, and Liu Leqi.
2025. “Linear Representation Transferability Hypothesis: Leveraging
Small Models to Steer Large Models.” *arXiv Preprint arXiv:2506.00653*.
<https://arxiv.org/abs/2506.00653>.

</div>

<div id="ref-burns2024weak" class="csl-entry">

Burns, Collin, Pavel Izmailov, Jan Hendrik Kirchner, Bowen Baker, Leo
Gao, Leopold Aschenbrenner, Yining Chen, et al. 2024. “Weak-to-Strong
Generalization: Eliciting Strong Capabilities with Weak Supervision.” In
*International Conference on Machine Learning (ICML)*.
<https://arxiv.org/abs/2312.09390>.

</div>

<div id="ref-burns2023discovering" class="csl-entry">

Burns, Collin, Haotian Ye, Dan Klein, and Jacob Steinhardt. 2023.
“Discovering Latent Knowledge in Language Models Without Supervision.”
In *International Conference on Learning Representations (ICLR)*.
<https://arxiv.org/abs/2212.03827>.

</div>

<div id="ref-chen2025persona" class="csl-entry">

Chen, Runjin, Andy Arditi, Henry Sleight, Owain Evans, and Jack Lindsey.
2025. “Persona Vectors: Monitoring and Controlling Character Traits in
Language Models.” *arXiv Preprint arXiv:2507.21509*.
<https://arxiv.org/abs/2507.21509>.

</div>

<div id="ref-christiano2018amplification" class="csl-entry">

Christiano, Paul, Buck Shlegeris, and Dario Amodei. 2018. “Supervising
Strong Learners by Amplifying Weak Experts.” *arXiv Preprint
arXiv:1810.08575*. <https://arxiv.org/abs/1810.08575>.

</div>

<div id="ref-dong2024contrans" class="csl-entry">

Dong, Weilong, Xinwei Wu, Renren Jin, Shaoyang Xu, and Deyi Xiong. 2024.
“ConTrans: Weak-to-Strong Alignment Engineering via Concept
Transplantation.” *arXiv Preprint arXiv:2405.13578*.
<https://arxiv.org/abs/2405.13578>.

</div>

<div id="ref-fierro2025weightsteering" class="csl-entry">

Fierro, Constanza, and Fabien Roger. 2026. “Steering Language Models
with Weight Arithmetic.” In *International Conference on Learning
Representations (ICLR)*. <https://arxiv.org/abs/2511.05408>.

</div>

<div id="ref-forethought_character" class="csl-entry">

Forethought. 2026. “The Importance of AI Character.” Forethought
research.
<https://www.forethought.org/research/the-importance-of-ai-character>.

</div>

<div id="ref-gemma2" class="csl-entry">

Gemma Team. 2024. “Gemma 2: Improving Open Language Models at a
Practical Size.” *arXiv Preprint arXiv:2408.00118*.
<https://arxiv.org/abs/2408.00118>.

</div>

<div id="ref-irving2018debate" class="csl-entry">

Irving, Geoffrey, Paul Christiano, and Dario Amodei. 2018. “AI Safety
via Debate.” *arXiv Preprint arXiv:1805.00899*.
<https://arxiv.org/abs/1805.00899>.

</div>

<div id="ref-qwen35omni" class="csl-entry">

Qwen Team. 2026. “Qwen3.5-Omni Technical Report.”
<https://arxiv.org/abs/2604.15804>.

</div>

<div id="ref-zhu2025sims" class="csl-entry">

Zhu, Rongyi, Yuhui Wang, Tanqiu Jiang, Jiacheng Liang, and Ting Wang.
2025. “Self-Improving Model Steering.” *arXiv Preprint
arXiv:2507.08967*. <https://arxiv.org/abs/2507.08967>.

</div>

<div id="ref-zou2023representation" class="csl-entry">

Zou, Andy, Long Phan, Sarah Chen, James Campbell, Phillip Guo, Richard
Ren, Alexander Pan, et al. 2023. “Representation Engineering: A Top-down
Approach to AI Transparency.” *arXiv Preprint arXiv:2310.01405*.
<https://arxiv.org/abs/2310.01405>.

</div>

</div>
