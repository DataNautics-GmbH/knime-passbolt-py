# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The Java↔Python pickle byte contract and the extension-↔-package compatibility
matrix are tracked separately in [`CONTRACT.md`](./CONTRACT.md).

## [0.1.1] — 2026-06-29

Security hardening of the pickle/broker seam. **No contract change** — the
pickle byte format, the `_build_from_broker` signature, and the broker URL
path are unchanged, so 0.1.1 is a drop-in replacement for 0.1.0.

### Security
- Broker URL validated structurally with `urlparse` against a loopback host
  allow-list (`127.0.0.1`, `localhost`, `::1`) at construction and at every
  fetch — closes the `startswith` userinfo bypass
  (`http://127.0.0.1:@evil.com/`).
- Bearer token validated: minimum length and printable-ASCII charset, so a
  tampered token cannot inject a header (CRLF) or raise mid-request.
- Fail-closed `wipe()`: the wrapper always ends marked wiped with its buffer
  reference dropped, even if in-place zeroization fails.
- Broker response capped at 64 KiB; all broker failure paths surface as
  `BrokerError`.
- Reviewed under the OWASP Code Review Guide v2 method (source→sink trace of
  the pickle/deserialization seam); all findings resolved. Added a
  validation test suite (`tests/test_secret_validation.py`).

## [0.1.0] — 2026-05-20

First public release. Compatible with the `knime-passbolt` KNIME extension
version `0.1.1.20260520` and later.

### Added
- `PassboltSecret` — lazy, wipeable wrapper around a Passbolt-resolved
  credential. Carries only a loopback broker URL, a bearer token, and an
  opaque session UUID; never the credential bytes.
- `_build_from_broker` — module-level pickle factory at the stable path
  `knime_passbolt._build_from_broker`, the target of the Java bridge's
  pickle `GLOBAL` opcode. Re-exported from `__init__.py`.
- Loopback broker client (`_broker.py`) that fetches the Authorization header
  on demand from `http://127.0.0.1:<port>/v1/auth-header`.
- Context-manager protocol: the fetched header is held in a `bytearray` and
  zeroed via `ctypes.memset` when the `with` block exits.
- `basic_auth_header()`, `session_uuid()`, `wipe()` accessors.
- Runnable examples with a mock broker (`httpbin_e2e`, `pdf_extract`,
  `docx_extract`).

[0.1.1]: https://github.com/DataNautics-GmbH/knime-passbolt-py/releases/tag/v0.1.1
[0.1.0]: https://github.com/DataNautics-GmbH/knime-passbolt-py/releases/tag/v0.1.0
