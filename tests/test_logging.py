"""The app's own log lines must reach stderr when it runs under uvicorn (issue #26).

A test with `caplog` cannot prove this: pytest installs its own handlers on the root logger, which
hides a missing logging setup. So these tests run the app module in a fresh interpreter.
"""

import os
import subprocess
import sys

CODE = (
    "import logging, app.main\n"
    "logging.getLogger('oncall.ask').info('probe-info-line')\n"
    "logging.getLogger('httpx').info('probe-httpx-chatter')\n"
)


def run(**env):
    # ONCALL_DISABLE_ANSWERER keeps the import from building the model and a database pool.
    full = {**os.environ, "ONCALL_DISABLE_ANSWERER": "1", **env}
    return subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, env=full)


def test_info_lines_reach_stderr_by_default():
    r = run()
    assert r.returncode == 0, r.stderr
    assert "probe-info-line" in r.stderr and "oncall.ask" in r.stderr


def test_httpx_chatter_stays_quiet():
    assert "probe-httpx-chatter" not in run().stderr


def test_the_level_can_be_raised_without_a_rebuild():
    assert "probe-info-line" not in run(ONCALL_LOG_LEVEL="WARNING").stderr


def test_a_bad_level_falls_back_to_info():
    assert "probe-info-line" in run(ONCALL_LOG_LEVEL="loud").stderr
