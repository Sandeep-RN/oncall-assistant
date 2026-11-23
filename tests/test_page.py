"""The page served at GET / (issue #6, PR A).

CI has no browser, so these tests check what can be checked from Python: that the page is served
with a strict Content-Security-Policy that really matches the file, that it can only render model
text as text, and that it has a message for every failure the edge or the app can send. How it
looks and behaves in a browser is checked by hand after each deploy.
"""

import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.page import INLINE_BLOCKS


@pytest.fixture
def page():
    # No answerer on purpose: the page must work whatever state the dependencies are in.
    app.state.answerer = None
    return TestClient(app).get("/")


def blocks(html: str, tag: str) -> list[str]:
    return [body for t, body in INLINE_BLOCKS.findall(html) if t == tag]


def test_the_page_is_served_as_html(page):
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "<textarea" in page.text and 'id="sources"' in page.text


def test_head_answers_like_get_but_without_a_body(page):
    # Found 2026-11-22 on the live site: HEAD / was a 405. Link previews, uptime checks and
    # `curl -I` use HEAD, and it must say the same as GET (RFC 9110): same headers, no body.
    head = TestClient(app).head("/")
    assert head.status_code == 200
    assert head.content == b""
    for name in ("content-type", "content-security-policy", "cache-control", "content-length"):
        assert head.headers[name] == page.headers[name], name


def test_the_page_is_not_cached_across_deploys(page):
    assert page.headers["cache-control"] == "no-cache"


def test_the_policy_allows_only_this_files_own_script_and_style(page):
    csp = page.headers["content-security-policy"]
    # Nothing is allowed by default; the page may talk only to its own origin.
    assert "default-src 'none'" in csp
    assert "connect-src 'self'" in csp
    for directive in ("base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert directive in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    # The hashes in the header are the hashes of the inline blocks actually served.
    for tag, directive in (("script", "script-src"), ("style", "style-src")):
        found = blocks(page.text, tag)
        assert len(found) == 1, f"expected exactly one inline <{tag}>"
        digest = base64.b64encode(hashlib.sha256(found[0].encode()).digest()).decode()
        assert re.search(rf"{directive} 'sha256-{re.escape(digest)}'", csp), directive


def test_other_security_headers_are_set(page):
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "no-referrer"


def test_nothing_is_loaded_from_elsewhere(page):
    # One file, no CDN: no external script, stylesheet, image or font.
    assert not re.search(r"<script[^>]*\ssrc=", page.text)
    assert "<link" not in page.text and "<img" not in page.text
    assert "@import" not in page.text and "url(" not in page.text


@pytest.mark.parametrize(
    "unsafe",
    ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function("],
)
def test_model_text_can_only_be_rendered_as_text(page, unsafe):
    # The answer and the notice are model or server text: they must never be parsed as HTML.
    assert unsafe not in blocks(page.text, "script")[0]


def test_citation_links_are_limited_to_the_platform_repos(page):
    script = blocks(page.text, "script")[0]
    assert "https://github.com/Sandeep-RN/" in script
    assert "noopener" in script


def test_the_question_box_enforces_the_api_limits(page):
    assert 'minlength="3"' in page.text and 'maxlength="500"' in page.text


@pytest.mark.parametrize("status", [413, 422, 429, 503])
def test_every_failure_status_has_its_own_message(page, status):
    # 413 and 429 come from Traefik as plain text (no JSON body); 422 and 503 come from the app.
    assert str(status) in blocks(page.text, "script")[0]


def test_the_page_says_where_the_question_goes(page):
    # The brief's data-handling promise: visitors are told their question leaves the cluster.
    text = page.text.lower()
    assert "groq" in text and "not stored" in text


def test_the_page_shows_saved_answers_with_a_clear_label(page):
    script = blocks(page.text, "script")[0]
    # `kind: "saved"` from /ask (a capacity limit) and the list from /saved (after a 503).
    assert '"saved"' in script and '"/saved"' in script
    # The brief: a saved answer counts as good only if it is clearly labelled as one.
    assert "saved answer" in page.text.lower()
    assert "not generated for your question" in page.text.lower()


def test_the_page_renders_markdown_with_elements_it_builds_not_with_html(page):
    # Found 2026-11-23 in the live page: the model's answers (and the saved ones) use fenced code
    # blocks, `inline code` and **bold**, and the page showed the raw ``` and ** characters. They
    # are drawn with createElement + textContent; no HTML is parsed (the test above forbids it).
    script = blocks(page.text, "script")[0]
    for needle in (
        'createElement("pre")',
        'createElement("code")',
        'createElement("strong")',
        "```",
    ):
        assert needle in script, needle


def test_both_the_live_answer_and_the_saved_answers_go_through_the_renderer(page):
    script = blocks(page.text, "script")[0]
    # A live answer (#answer) and each saved answer are rendered by the same function, so a code
    # block looks the same in both. Neither may be set with textContent directly any more.
    assert "answer.textContent" not in script
    assert "text.textContent" not in script
    assert script.count("rich(") >= 3  # the definition and two calls


def test_a_429_uses_the_edges_retry_after_and_falls_back_without_it(page):
    # Checked live 2026-11-23: Traefik's 429 is plain text with `Retry-After: 15`. The page used to
    # say "wait a minute" whatever the edge said. It reads the header (seconds only, clamped) and
    # keeps the old wording when the header is missing or is not a number.
    script = blocks(page.text, "script")[0]
    assert '"Retry-After"' in script
    assert "429" in script and "Please wait a minute" in script  # the fallback stays
    assert "parseInt" in script  # the header is a number of seconds, never trusted as text


def test_the_page_can_send_a_demo_token_and_explains_a_rejected_one(page):
    script = blocks(page.text, "script")[0]
    # The token goes in a header (never the URL), is kept only for the tab (sessionStorage, not
    # localStorage), and a 401 gets its own message: a wrong token is never silently downgraded.
    assert "X-Demo-Token" in script
    assert "sessionStorage" in script and "localStorage" not in script
    assert "401" in script
    assert 'type="password"' in page.text and 'autocomplete="off"' in page.text


def test_the_page_is_not_part_of_the_api_schema(page):
    # GET / is a page, not an API call: it stays out of the API schema. The schema is built
    # in-process because /openapi.json is not served by default (issue #47).
    assert "/" not in app.openapi()["paths"]


# --- Cross-links and the "Built with" row (issue #66) ---------------------------------------

REPO = "https://github.com/Sandeep-RN/oncall-assistant"
DEMO_REPO = "https://github.com/Sandeep-RN/oci-k8s-gitops-demo"
ALLOWED_LINK_PREFIXES = (REPO, DEMO_REPO, "https://demo.sandeeprn.in")


def markup_links(html: str) -> list[str]:
    """Every href written in the static markup (the script builds its own, tested above)."""
    without_script = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL)
    return re.findall(r'<a\s[^>]*href="([^"]+)"', without_script)


def test_the_header_links_to_the_platform_site_and_the_repo(page):
    header = re.search(r"<header.*?</header>", page.text, re.DOTALL)
    assert header, "a <header> with a nav is expected"
    nav = header.group(0)
    assert re.search(r'<nav [^>]*aria-label="', nav)
    assert 'href="https://demo.sandeeprn.in"' in nav
    assert f'href="{REPO}"' in nav


def test_every_static_link_goes_to_a_known_place_and_is_safe(page):
    links = markup_links(page.text)
    assert links
    for href in links:
        assert href.startswith(ALLOWED_LINK_PREFIXES), href
    # Links that open in a new tab must not hand it window.opener.
    for tag in re.findall(
        r"<a\s[^>]*>", re.sub(r"<script.*?</script>", "", page.text, flags=re.DOTALL)
    ):
        if 'target="_blank"' in tag:
            assert "noopener" in tag, tag


def test_no_inline_event_handlers_were_added(page):
    # The policy has no 'unsafe-inline' for scripts: an on* attribute would be dead and a smell.
    assert not re.search(
        r"\son[a-z]+\s*=", re.sub(r"<script.*?</script>", "", page.text, flags=re.DOTALL)
    )


def test_the_built_with_row_lists_only_parts_the_repo_documents(page):
    row = re.search(r'<ul class="stack".*?</ul>', page.text, re.DOTALL)
    assert row, "a 'Built with' list is expected"
    text = re.sub(r"<[^>]+>", " ", row.group(0))
    for part in (
        "FastAPI",
        "ONNX Runtime",
        "pgvector",
        "Groq",
        "k3s",
        "Argo CD",
        "Traefik",
        "Sealed Secrets",
    ):
        assert part in text, part
    # Every badge is a link to an ADR or a source file, never a bare logo.
    assert row.group(0).count("<li>") == row.group(0).count("<a ")


def test_the_resource_cap_line_matches_adr_0025(page):
    # ADR 0025 (platform repo) and CLAUDE.md: 1 GiB of memory and 1 CPU for the whole namespace.
    assert "1 GiB" in page.text and "1 CPU" in page.text
    assert "0025-second-application-on-the-node-inside-a-hard-cap.md" in page.text
