# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- **Preferred:** GitHub private vulnerability reporting — repository **Security**
  tab → *Report a vulnerability*.
- **Email:** info@datanautics.net

We aim to acknowledge within 5 business days and to share a remediation
timeline after triage. Please allow coordinated disclosure before publishing
any write-up.

## Security model

`knime-passbolt-py` deserializes a pickle byte stream emitted by the
`knime-passbolt` KNIME extension. The `PassboltSecret` wrapper:

- carries only a loopback broker URL, a short-lived bearer token, and an opaque
  session UUID — never the credential bytes;
- validates the broker URL structurally (`urlparse`) as loopback at
  construction and at every fetch, closing the `startswith` userinfo bypass;
- validates the bearer token (minimum length + printable ASCII) to prevent
  header injection;
- holds the fetched `Authorization` header in a `bytearray` that is zeroed
  (`ctypes.memset`) when the `with` block exits;
- never serializes credential bytes, even via accidental re-pickling
  (`__reduce__` re-pickles to the broker handshake only).

The pickle/deserialization seam was reviewed under the OWASP Code Review Guide
v2 method. Per-release security notes are in [`CHANGELOG.md`](./CHANGELOG.md).

## Known limits

In-process Python code can read the header `bytearray` while the `with` block
is open; CPython provides no hardware-enforced isolation. Do not persist the
pickle to any location an attacker can read — the bearer token is replayable
against the loopback broker for the lifetime of the bridge node's execution.

## Supply-chain provenance

Releases are published to PyPI from GitHub Actions via OIDC Trusted Publishing
(no stored API token) and ship PEP 740 attestations linking each artifact to
the workflow run that produced it.
