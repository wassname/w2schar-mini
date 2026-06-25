# Artificial Analysis open-weights LLM leaderboard (scraped 2026-06-25)

Source: artificialanalysis.ai LLM leaderboard, open-weights view, pasted by wassname
this session. Used for the w2s teacher/student capability-gap decision (see
RESEARCH_JOURNAL 2026-06-25 c/d/e).

Column notes:
- `Intelligence` = Artificial Analysis Intelligence Index. `*` is AA's own marker
  (estimated / independent eval pending), copied verbatim.
- `Price` = USD per 1M tokens (blended), as shown.
- The last three columns were unlabeled in the scrape. Inferred from AA's standard
  layout as Output Speed (tokens/s), Latency (time-to-first-token, s), and End-to-end
  response time (s, higher for reasoning rows). Treat these three labels as my inference,
  not confirmed from the page.
- Duplicate model names are the reasoning vs non-reasoning variants (the page had a
  "Reasoning model" toggle): the higher-Intelligence row is reasoning-on, the lower is
  reasoning-off. Rows kept in the pasted order (descending Intelligence).
- Our setup is marked: teacher target `qwen/qwen3.5-9b` and dense student
  `Qwen/Qwen3.6-27B` are NOT on this list (the 9B and a 27B-dense Qwen3.6 are absent;
  closest listed is `Qwen3.6 35B A3B`, a MoE). `Gemma 4 31B` IS listed at 25.

| Model | Org | Context | Intelligence | Price $/1M | OutSpd tok/s | TTFT s | E2E s |
|---|---|---|---|---|---|---|---|
| Qwen3.5 27B (reasoning) | Alibaba | 262k | 34* | 0.50 | 83 | 5.81 | 36.10 |
| Qwen3.6 35B A3B (reasoning) | Alibaba | 262k | 32 | 0.37 | 176 | 2.32 | 35.83 |
| Qwen3.5 27B | Alibaba | 262k | 29* | 0.50 | 91 | 5.85 | 11.32 |
| Qwen3.5 35B A3B (reasoning) | Alibaba | 262k | 29* | 0.42 | 172 | 2.26 | 16.79 |
| Gemma 4 26B A4B | Google | 256k | 26 | 0.14 | -- | -- | -- |
| **Gemma 4 31B** | Google | 256k | 25* | 0.17 | 45 | 2.28 | 13.27 |
| Qwen3.6 35B A3B | Alibaba | 262k | 24* | 0.56 | 197 | 2.32 | 4.86 |
| Qwen3.5 35B A3B | Alibaba | 262k | 23* | 0.42 | 193 | 2.23 | 4.83 |
| GLM-4.7-Flash (reasoning) | Z AI | 200k | 23* | 0.10 | 83 | 1.64 | 31.78 |
| Gemma 4 12B | Google | 256k | 22* | 0.12 | 126 | 2.41 | 22.19 |
| Gemma 4 26B A4B | Google | 256k | 20* | 0.16 | 41 | 2.01 | 14.22 |
| Seed-OSS-36B-Instruct | ByteDance Seed | 512k | 18* | 0.25 | 33 | 3.05 | 79.82 |
| Qwen3 30B A3B 2507 (reasoning) | Alibaba | 262k | 16* | 0.44 | 143 | 2.52 | 20.01 |
| GLM-4.7-Flash | Z AI | 200k | 16* | 0.10 | 122 | 1.91 | 6.02 |
| Qwen3 Coder 30B A3B | Alibaba | 262k | 14* | 0.25 | 102 | 2.72 | 7.61 |
| QwQ-32B | Alibaba | 131k | 13* | 0.69 | 32 | 2.12 | 96.03 |
| Qwen3 VL 30B A3B (reasoning) | Alibaba | 256k | 13* | 0.26 | 112 | 2.25 | 24.64 |
| Gemma 4 12B (Non-reasoning) | Google | 262k | 13* | 0.12 | 136 | 2.71 | 6.39 |
| Magistral Small 1.2 | Mistral | 128k | 12* | 0.60 | 105 | 0.92 | 24.75 |
| Qwen3 VL 8B (reasoning) | Alibaba | 256k | 11* | 0.37 | 116 | 2.39 | 23.87 |
| Qwen3 32B (reasoning) | Alibaba | 32.8k | 10* | 0.23 | 97 | 2.61 | 28.47 |
| Qwen3 14B (reasoning) | Alibaba | 32.8k | 10* | 0.43 | 62 | 2.80 | 43.36 |
| Qwen3 VL 30B A3B | Alibaba | 256k | 10* | 0.24 | 114 | 2.30 | 6.67 |
| Ministral 3 14B | Mistral | 256k | 10* | 0.20 | 80 | 0.89 | 7.16 |
| Qwen3 Omni 30B A3B (reasoning) | Alibaba | 65.5k | 10* | 0.32 | 83 | 2.08 | 32.22 |
| Qwen3 30B (reasoning) | Alibaba | 32.8k | 9* | 0.13 | 107 | 2.21 | 25.65 |
| Devstral Small | Mistral | 256k | 9* | 0.12 | 30 | 1.22 | 17.98 |
| Qwen3 30B A3B 2507 | Alibaba | 262k | 9* | 0.18 | 169 | 1.97 | 4.92 |
| NVIDIA Nemotron Nano 12B v2 VL (reasoning) | NVIDIA | 128k | 9* | 0.24 | 256 | 0.44 | 10.18 |
| Ministral 3 8B | Mistral | 256k | 9* | 0.15 | 87 | 0.80 | 6.52 |
| Qwen3 32B | Alibaba | 32.8k | 9* | 0.19 | 94 | 2.61 | 7.90 |
| Qwen3 VL 8B | Alibaba | 256k | 8* | 0.23 | 122 | 2.41 | 6.51 |
| Qwen3 8B (reasoning) | Alibaba | 131k | 7* | 0.21 | 38 | 3.89 | 69.41 |
| Qwen3 14B | Alibaba | 32.8k | 7* | 0.29 | 63 | 2.80 | 10.72 |
| Solar Mini | Upstage | 4.1k | 6* | 0.15 | -- | -- | -- |
| Qwen3 Omni 30B A3B | Alibaba | 65.5k | 5* | 0.32 | 96 | 1.94 | 7.14 |
| Qwen3 8B | Alibaba | 32.8k | 5* | 0.18 | 38 | 3.85 | 16.99 |
| Phi-4 | Microsoft | 16k | 5* | 0.16 | 35 | 2.13 | 16.36 |
| Mistral Small (Sep) | Mistral | 32.8k | 5* | 0.24 | 168 | 0.79 | 3.77 |
| NVIDIA Nemotron Nano 12B v2 VL | NVIDIA | 128k | 5* | 0.24 | 211 | 1.12 | 3.49 |
| Reka Flash 3 | Reka AI | 128k | 4* | 0.26 | -- | -- | -- |
| Llama 3.2 11B (Vision) | Meta | 128k | 3* | 0.25 | 49 | 0.76 | 10.87 |
| Mistral 7B | Mistral | 8.19k | 2* | 0.20 | 88 | 0.81 | 6.52 |
| Command-R (Mar) | Cohere | 128k | 2* | 0.60 | -- | -- | -- |

## Relevance to our w2s pairing

- `Gemma 4 31B` = 25, vs `Qwen3.5 27B` = 34 reasoning / 29 non-reasoning. This is the
  entry-(c) finding in one line: the qwen teacher line is above Gemma 4 31B with reasoning
  on, so a qwen-teacher -> gemma-4-31b run is not a real w2s gap (RJ 2026-06-25e).
- Neither our exact teacher (`qwen/qwen3.5-9b`) nor our exact dense student
  (`Qwen/Qwen3.6-27B`) appears here. Flag for follow-up: confirm those two model ids are
  real/served, since the index lists `Qwen3.6 35B A3B` (MoE) rather than a 27B dense.
