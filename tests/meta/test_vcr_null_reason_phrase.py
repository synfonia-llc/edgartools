"""Cassettes with no recorded reason phrase must replay on supported vcrpy.

79 of the suite's cassettes store ``message: null`` (they were recorded through
vcrpy's httpcore stub). Supported vcrpy 8.3 needs ``tests/_vcr_compat.py`` to
fill the phrase in; vcrpy 8.4+ handles it upstream. These tests replay through
a real VCR, the way a cassette-backed test does, and check that installing the
compatibility fix again preserves working replay in either case.
"""
import importlib
import importlib.util

import pytest
import vcr

from tests import _vcr_compat

pytestmark = pytest.mark.fast

URL = "http://127.0.0.1:9/edgartools-vcr-null-phrase/{name}.txt"

INTERACTION = """\
- request:
    body: ''
    headers: {{}}
    method: GET
    uri: {uri}
  response:
    body:
      string: {name}
    headers:
      Content-Type:
      - text/plain
    status:
      code: {code}
      message: {message}
"""

# name -> (status code, phrase as written in the cassette, phrase expected on replay)
CASES = {
    "null-ok": (200, "null", "OK"),
    "null-not-found": (404, "null", "Not Found"),
    "empty": (200, "''", "OK"),
    "recorded": (200, "Peachy", "Peachy"),
}


@pytest.fixture
def replay_only(tmp_path, vcr_config):
    interactions = "".join(
        INTERACTION.format(uri=URL.format(name=name), name=name, code=code, message=message)
        for name, (code, message, _) in CASES.items()
    )
    (tmp_path / "phrases.yaml").write_text(f"interactions:\n{interactions}version: 1\n")
    config = {**vcr_config, "cassette_library_dir": str(tmp_path), "record_mode": "none"}
    return vcr.VCR(**config)


# httpx2 is what edgartools sends requests through. Plain httpx is not a
# dependency, but edgartools[ai] installs it (the MCP SDK needs it) and vcrpy
# routes both through the same stub, so it is checked wherever it is present.
LIBRARIES = ["httpx2", pytest.param("httpx", marks=pytest.mark.skipif(
    importlib.util.find_spec("httpx") is None, reason="plain httpx is not installed"))]


@pytest.mark.parametrize("library", LIBRARIES)
@pytest.mark.parametrize("name", list(CASES))
def test_replay_supplies_the_reason_phrase(replay_only, name, library):
    code, _, expected_phrase = CASES[name]
    http = importlib.import_module(library)

    with replay_only.use_cassette("phrases.yaml", allow_playback_repeats=True):
        response = http.get(URL.format(name=name))

    assert response.status_code == code
    assert response.reason_phrase == expected_phrase
    assert response.text == name


def test_the_compat_fix_is_idempotent():
    """Conftest has already configured a deserializer that handles null phrases."""
    from vcr.stubs import httpx_stubs

    current = httpx_stubs._deserialize_response
    assert _vcr_compat.install_null_reason_phrase_fix() is False
    assert httpx_stubs._deserialize_response is current
    assert _vcr_compat._replays_null_phrase(current)
