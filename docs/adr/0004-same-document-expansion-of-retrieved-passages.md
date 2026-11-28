# 0004. When most retrieved passages share a document, add more of its sections

Status: Accepted (2026-11-28). Amends [ADR 0002](0002-cite-or-refuse-one-openai-compatible-call.md),
which gives the model the top 5 passages. Issue #74.

## Context
- The page's own example question, "The redirect SLO burn-rate alert is firing. What do I check
  first?" (eval question A01), got cited but wrong answers on the live site: three of three
  started with the synthetic probe. The answer is in the runbook's "Triage (5 minutes)" section,
  which ranked 10th (pinned corpus) and 11th (latest docs). All five passages the model got came from
  the same runbook, just not that section. The citation check (ADR 0002) passed, because the cited
  passages were real; they were the wrong ones.
- A01 had been a recorded miss since the first eval run (#13): "right runbook, wrong section".
- Changes were measured on the whole eval set (28 answerable questions), on both the pinned corpus
  and the docs at each repo's head, with no model calls. The model gets about 1,000 words today.

| Change | Pinned | Latest | A01 | Prompt |
|---|---|---|---|---|
| Today: top 5 | 25/28 | 24/28 | missed | 1.0x |
| Top 10 | 28/28 | 26/28 | pinned only | about 1.9x |
| Keyword + meaning (hybrid ranking) | 25/28 | 25/28 | missed | about 1.0x; gains A08, loses A15 |
| Rename the Triage heading to the question's words | 26/28 | 25/28 | found | 1.0x; tuned to one question |
| **This record: same-document expansion** | **26/28** | **25/28** | **found** | **about 1.05x on average; no question lost** |

## Decision
1. Search returns the top 20 candidates. The model gets the top 5 as before.
2. If at least 4 of those 5 come from one document (same repo and path), up to 3 more sections of that
   document are added from the 20, in rank order, after the 5. They are numbered 6 to 8 and can be
   cited like the others.
3. The answerer and the retrieval eval call the same function (`app/index/select.py`), so the eval
   scores exactly what a visitor gets. `python -m app.evals --no-same-document` scores the old rule.
4. `RETRIEVE_SAME_DOCUMENT=off` in the Deployment turns it off without a new image.

## Consequences
- On the eval set the rule fires on 7 of 28 answerable questions and on 1 unanswerable one (U03),
  and changes the result of A01 only. The prompt grows by at most 3 passages (about 8 x 450 words at
  the cap); the daily token budget (ADR 0003) absorbs it.
- The rule was designed after seeing A01, and the eval set has no held-out part yet (#14), so the
  numbers above cannot show that it generalises. A stricter version (all 5 from one document) fired
  on A01 only and was rejected as tuned to it.
- Retrieval finding the section does not prove the answer uses it. Answers with and without the rule
  were compared on a few questions before release (see the pull request); the answer eval of M2 is
  the real measure.

## At scale
A corpus with many long documents would make "4 of 5 from one document" common and the prompt
longer more often. A per-document cap, or re-ranking sections inside the chosen document, would then
be the next step.
