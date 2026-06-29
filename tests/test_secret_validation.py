# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the security-relevant validation in PassboltSecret.

These cover the branches added after the 2026-06-28 OWASP review:
loopback URL parsing (userinfo-bypass), token charset validation, and the
fail-closed wipe(). Broker round-trips are not exercised here (no live broker).
"""

import pytest

from knime_passbolt import PassboltSecret

VALID_TOKEN = "x" * 40


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:@evil.com/",  # userinfo trick — startswith() would pass
        "http://evil.com/v1/auth-header",
        "https://127.0.0.1:5/",  # wrong scheme
        "ftp://127.0.0.1:5/",
        12345,  # not a string
    ],
)
def test_rejects_non_loopback_url(url):
    with pytest.raises(ValueError):
        PassboltSecret(url, VALID_TOKEN, "session")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:54321/v1/auth-header",
        "http://localhost:5/x",
    ],
)
def test_accepts_loopback_url(url):
    secret = PassboltSecret(url, VALID_TOKEN, "session")
    assert secret.session_uuid() == "session"


@pytest.mark.parametrize(
    "token",
    [
        VALID_TOKEN[:-2] + "\r\n",  # CRLF header injection
        VALID_TOKEN[:-1] + "\x00",  # control char
        VALID_TOKEN[:-1] + "é",  # non-ASCII
        "short",  # below length floor
        42,  # not a string
    ],
)
def test_rejects_bad_token(token):
    with pytest.raises(ValueError):
        PassboltSecret("http://127.0.0.1:5/", token, "session")


def test_repr_leaks_no_secret():
    secret = PassboltSecret("http://127.0.0.1:5/", VALID_TOKEN, "session-uuid-value")
    text = repr(secret)
    assert VALID_TOKEN not in text
    assert "session-uuid-value" not in text  # only the [:8] prefix is shown


def test_wipe_is_fail_closed_with_exported_buffer():
    """If the buffer is exported (memoryview held), zeroization can't run in
    place — but the wrapper must still end marked wiped with the ref dropped."""
    secret = PassboltSecret("http://127.0.0.1:5/", VALID_TOKEN, "session")
    secret._buf = bytearray(b"composed-header-bytes")
    view = memoryview(secret._buf)  # forces BufferError on both zeroization paths
    try:
        secret.wipe()  # must not raise
    finally:
        view.release()
    assert secret._wiped is True
    assert secret._buf is None


def test_wipe_zeroes_buffer_when_not_exported():
    secret = PassboltSecret("http://127.0.0.1:5/", VALID_TOKEN, "session")
    secret._buf = bytearray(b"composed-header-bytes")
    secret.wipe()
    assert secret._wiped is True
    assert secret._buf is None


def test_use_after_wipe_raises():
    secret = PassboltSecret("http://127.0.0.1:5/", VALID_TOKEN, "session")
    secret.wipe()
    with pytest.raises(RuntimeError):
        secret.basic_auth_header()
