
# 2026-06-20 11:53:37

should it have some basic info? like a paragraph abotu the permite "we are seeing if weight-steering will allow a weak model to align a larger model. We ask {teacher} to align {students} charector according to {forethougth
    essay?}. It does this by 1) choosing a lesson 2) steering personas 3) selection student answers 4) training a weigth steering adapter 5) passing or failing the trained student

    Why is this interesting? [Weak to strong alignent is](url).. sentance. We thinkg that steering has suseful alignmment properties: it's self-supervised so it doesn't need labels, it's internal so quite resistance to the reward hacking that
    distance RL objectives are prone to, and it provides a simple interface that allow a weak teacher to steer a strong student moral charector"

    this migth be good for a human intro in readme if you fill our the url fix spelling? so in index templ and readme? on in index.html also link to our repo please

---

 "had to empower the weak model by having it only do easy tasks like 1) selection and 2) judgement. Not harder things like generation or editing." is how I would say it. and there more in the LCAUDE.md we coudl distill into a nice paragraph with
  opening framing
  --

Here's a recent weak to strong run. A small 9b model driving a 27b model.

It's kind of working, but I had to empower the weak model by having it only do easy tasks like 1) selection and 2) judgement. Not harder things like generation or editing.

Because writing personas is an open question I had to give it a prewritten library of personas to select from.

It also selects good weight steering example completions from ~100 filtered options each round.

Hopefully this means it's back on track https://github.com/wassname/w2schar-mini


---

› oh it migth be worth mentioning what weight steering is so. Steering is promising but has a repuation fro being unreliably. A new type of steering https://github.com/safety-research/weight-steering is interesting because it uses the models own
  completions to train adapters and find a direction in the space of weight changes. I've found it more reliable and stable than normal steering, as this repo shows it can also be appleid iteratitivly, opening up applicates like auto research sstyle
  charecter steering. So this repo takes a modification of weigh steering.

  Normal weight steering is not optimised, we modify using some of the insights from our previous antipasto work https://arxiv.org/pdf/2601.07473
  - weight steering generate completions with personas, and then remove the personas to have new vehavioural pairs
    - I also filter this and use them as trictly contrastive pairs
  - weight steering trains two adapter
    - I train one adapter with a parametrised intervention
  - weight steering always takes the trained C=1 strength, we calibrate the maximum coherent strength
