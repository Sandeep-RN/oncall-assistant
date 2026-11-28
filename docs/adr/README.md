# Architecture decision records (application)

Decisions about the assistant's own code. Platform decisions (how it shares the node, its resource
cap, its namespace and AppProject) are in the demo repo:
[ADR 0025](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/docs/adr/0025-second-application-on-the-node-inside-a-hard-cap.md).

One record per decision, numbered from 0001. A record is not rewritten when things change: the
status line points to the record that amends or replaces it.

| # | Decision | Status |
|---|---|---|
| [0001](0001-local-onnx-embeddings-on-python-314.md) | Local ONNX embeddings with bge-small-en-v1.5, on Python 3.14 (no cp315 ONNX Runtime yet) | Accepted |
| [0002](0002-cite-or-refuse-one-openai-compatible-call.md) | Answers cite or refuse, through one OpenAI-compatible call (no SDK, no retries, 503 when unavailable) | Accepted, partly replaced by 0003, amended by 0004 |
| [0003](0003-saved-answers-on-capacity-limits-and-a-daily-budget.md) | Saved answers when the free tier is at its limit (capacity 200, faults 503); daily token budget in Postgres, one writable table, demo token | Accepted |
| [0004](0004-same-document-expansion-of-retrieved-passages.md) | When 4 of the top 5 passages share a document, add up to 3 more of its sections (eval A01, issue #74) | Accepted |
