# oncall-assistant

An on-call assistant for a platform team, built as a mock customer engagement and deployed onto the existing k3s platform of oci-k8s-gitops-demo.

## Language

### The engagement

**SRE-FDE**:
An engineer who deploys an AI application into a customer's platform (the forward-deployed half) and runs it to measured targets such as SLOs, eval scores and cost limits (the SRE half).
_Avoid_: AIOps engineer (AIOps is what this app does, not the role), ML engineer

**Platform team**:
The customer in this engagement: the team that owns the platform and its runbooks, role-played by the owner and labelled as such.
_Avoid_: client, user (users are the on-call engineers)

**On-call assistant**:
The application delivered to the platform team: it answers on-call questions from the team's documents, with citations, and later reads live state.
_Avoid_: chatbot, copilot

**Live state**:
The platform's current condition as the assistant may read it: firing alerts, application health, pod events. Read-only.

**Engagement**:
The project presented as work for a customer: a brief, success criteria, a delivery and a handover.
_Avoid_: POC, side project

**Customer brief**:
The one-page statement of the customer's problem, users, documents, constraints and success criteria.
_Avoid_: requirements doc, spec

**Platform**:
The customer's existing environment that the application is deployed into, together with its rules; here, the k3s node and its shared services from oci-k8s-gitops-demo.
_Avoid_: infra, "the cluster" (when the rules matter, not only the machine)

### Answering

**RAG (retrieval-augmented generation)**:
Answering a question by first retrieving the passages that match it, then having the model answer only from those passages.
_Avoid_: chatbot, AI search

**Passage**:
A piece of a document small enough to be retrieved and cited on its own.
_Avoid_: snippet; "chunk" only in code

**Citation**:
A pointer from a statement in an answer to the passage that supports it.

**Refusal**:
The answer "I don't know", given when the documents do not hold the answer.
_Avoid_: fallback, error

**Agent**:
A model that chooses which tools to call, in a loop, until a task is done.
_Avoid_: bot, copilot (when no tools are involved)

**Tool**:
An action an agent may call, such as a search or a read of live state.

### Quality

**Eval**:
A fixed set of questions with expected answers and sources, and the scoring of retrieval, answers and refusals against it.
_Avoid_: test (unqualified), benchmark

**Daily LLM budget**:
The share of the provider's daily free allowance that public visitors may use; the rest is kept for demo-token holders (evals use a separate key, not this allowance). When it is spent, the assistant shows saved example answers instead of live ones.
_Avoid_: quota (that word is the provider's limit or the OCI quota policy)

**Live answer**:
An answer written by the model for this question from retrieved passages.

**Saved answer**:
A pre-written, cited answer to an example question, shown and clearly labelled when the free model tier is at its limit: the daily LLM budget is spent, the provider answers 429, or two answers are already running. A real fault (timeout, provider error, database down) is not covered: it stays an error.
_Avoid_: cached answer, fallback

**Demo token**:
A named secret given to the owner and to reviewers; it lifts the public share of the daily LLM budget (not the provider's own limit) and is the only way to reach the live-state agent.
_Avoid_: API key (that is the credential for the LLM provider)

**Fine-tuning**:
Changing a model's weights by training it on examples.
_Avoid_: "tuning" for changes to retrieval or prompts; call those retrieval or prompt changes
