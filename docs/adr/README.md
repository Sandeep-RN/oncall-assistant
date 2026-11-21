# Architecture decision records (application)

Decisions about the assistant's own code. Platform decisions (how it shares the node, its resource
cap, its namespace and AppProject) are in the demo repo:
[ADR 0025](https://github.com/Sandeep-RN/oci-k8s-gitops-demo/blob/main/docs/adr/0025-second-application-on-the-node-inside-a-hard-cap.md).

One record per decision, numbered from 0001. A record is not rewritten when things change: the
status line points to the record that amends or replaces it.

| # | Decision | Status |
|---|---|---|
| [0001](0001-local-onnx-embeddings-on-python-314.md) | Local ONNX embeddings with bge-small-en-v1.5, on Python 3.14 (no cp315 ONNX Runtime yet) | Accepted |
| [0002](0002-cite-or-refuse-one-openai-compatible-call.md) | Answers cite or refuse, through one OpenAI-compatible call (no SDK, no retries, 503 when unavailable) | Accepted |
