from backend.app.core.snapshot import (
    canonical_json,
    code_fingerprint,
    make_run_id,
    sha256_hex,
)


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_sha256_is_stable():
    assert sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_run_id_changes_with_request_code_data_and_mode():
    payload = {"name": "base", "n_paths": 100}
    base = make_run_id(payload, "0.1.0", "abc123", "none", "llm")
    assert len(base) == 16
    assert base == make_run_id(payload, "0.1.0", "abc123", "none", "llm")
    assert base != make_run_id(payload, "0.1.0", "abc123", "none", "template")
    assert base != make_run_id(payload, "0.1.0", "def456", "none", "llm")
    assert base != make_run_id(payload, "0.2.0", "abc123", "none", "llm")
    assert base != make_run_id(payload, "0.1.0", "abc123", "v1", "llm")
    assert base != make_run_id(
        {"name": "other", "n_paths": 100}, "0.1.0", "abc123", "none", "llm"
    )


def test_code_fingerprint_is_stable():
    first = code_fingerprint()
    second = code_fingerprint()
    assert first == second
    assert len(first) == 12
