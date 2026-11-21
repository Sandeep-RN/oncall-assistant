"""On-call assistant API.

Only the liveness endpoint exists so far; the question endpoint, retrieval and
the page arrive in the other M1 issues (see the milestone).
"""

from fastapi import FastAPI

app = FastAPI(title="oncall-assistant")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    # Liveness only: answers if the process is up. It must not touch the
    # database or the model provider, or an outage there would restart the pod
    # for no reason (same idea as ADR 0016 in the platform repo).
    return {"status": "ok"}
