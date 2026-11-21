"""Ask one question from the command line, with the same wiring as the app.

    python -m app.answer "How do I roll back a bad deploy?"
    LLM_PROVIDER=kodekey python -m app.answer "..."      # the development key, laptop only

Needs the model files, the index (PG* or DATABASE_URL) and a provider key in the environment.
"""

from __future__ import annotations

import json
import sys

from app.answer.service import Unavailable
from app.main import build_answerer


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    answerer, (pool, http) = build_answerer()
    try:
        result = answerer.ask(args[0])
        print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
        return 0
    except Unavailable as e:
        print(json.dumps({"kind": "unavailable", "reason": e.reason, "notice": e.notice}))
        return 1
    finally:
        pool.close()
        http.close()


if __name__ == "__main__":
    raise SystemExit(main())
