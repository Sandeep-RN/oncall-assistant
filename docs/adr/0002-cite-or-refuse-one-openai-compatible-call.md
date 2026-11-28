# 0002. Answers cite or refuse, through one OpenAI-compatible call

Status: Accepted (2026-11-22). Partly replaced by [ADR 0003](0003-saved-answers-on-capacity-limits-and-a-daily-budget.md):
a 429 or a busy server now answers 200 with a saved answer; the other failures stay 503. Amended by
[ADR 0004](0004-same-document-expansion-of-retrieved-passages.md): up to 3 more passages of the same document.

## Context
The customer brief asks for short answers that cite the exact document and section, and for
"I don't know" when the documents do not cover the question. The public demo uses Groq's free tier
and development and evals use KodeKey (planning, round 3); both serve `gpt-oss-120b`.

Checked on 2026-11-22:

- **Both providers speak the same OpenAI-compatible API** (`POST /chat/completions`) and accept
  `reasoning_effort: "low"`. The same small question gave the same answer from both in about 0.5 s,
  with 6 to 11 reasoning tokens.
- **Similarity scores cannot decide a refusal.** On the eval set v0 (#8), the best passage of an
  answerable question scored 0.62 to 0.85 and of an unanswerable one 0.62 to 0.78. Any threshold
  either refuses real questions or answers unanswerable ones.
- **The free tier is small:** 30 requests and 8K tokens a minute. A slow or repeated call costs
  both latency (the target is 95% of live answers within 8 s) and budget.

## Decision
- **One function, no provider SDK.** A plain `httpx` call to `{base_url}/chat/completions`, chosen
  by `LLM_PROVIDER` (`groq` in the cluster, `kodekey` on the laptop). Timeouts are explicit (3 s to
  connect, 7 s in total) and there are no retries: a 429 means wait, and a retry breaks the latency
  target. Temperature 0, `reasoning_effort: "low"`, a cap on the answer's length.
- **The model cites or refuses.** It gets the top 5 passages numbered `[1]` to `[5]`, each with its
  heading path, and must cite `[n]` after every claim, or reply exactly "I don't know". Passage text
  is data, not instructions.
- **The app checks the citations.** Numbers that are not one of the passages are dropped. **An
  answer with no valid citation is turned into a refusal.** It is stricter than strictly needed,
  but an uncited answer is exactly what the brief rules out.
- **No answer is better than a slow or broken one.** A 429, a timeout, a 5xx or a malformed reply
  gives HTTP 503 with a notice saying the live answer is unavailable. Issue #6 adds saved answers to
  the same place. At most two model calls run at once; a third request gets the same 503 at once,
  which protects the pod's memory and the provider's per-minute limit.
- **Questions are not kept.** Logs hold a short hash and the length of the question, never its
  text. Each response carries its retrieval and generation times and token counts, for the metrics
  in M2.

## Consequences
- Whether every claim is really supported by the passage it cites is not checked here. That is the
  answer eval in M2 (a model as judge, on KodeKey).
- Some correct answers will be refused because the model forgot to cite. The refusal rate is
  measured in M2; a high rate is a prompt problem to fix, not a reason to drop the check.
- Measured on 2026-11-22 (5 eval questions, both providers, the pinned corpus): 2.0 to 2.5K prompt
  tokens and 25 to 240 completion tokens per answer, so about 3 live answers a minute on Groq's
  8K-tokens-a-minute free tier. Generation took 0.5 to 1.3 s; retrieval 0.1 to 0.2 s.
- The first live check found gpt-oss citing only with fullwidth brackets, `【1】`, which the first
  parser did not read: two correct answers became "uncited" refusals. The parser now accepts both
  styles and shows `[n]`. The check caught a real model habit that unit tests written from the
  prompt could not.
- An answer can still add a claim its citation does not support (one live answer added "restores
  are done from the latest dump only"). Catching that is the M2 answer eval's job.

## At scale
A model gateway with per-tenant budgets, retries with backoff and fallback between providers, and
streamed answers; citation checking by a second, smaller model; questions kept (with consent) to
grow the eval set from real use.
