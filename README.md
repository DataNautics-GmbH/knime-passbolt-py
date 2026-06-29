# knime-passbolt-py

[![PyPI version](https://img.shields.io/pypi/v/knime-passbolt-py.svg)](https://pypi.org/project/knime-passbolt-py/)
[![Python versions](https://img.shields.io/pypi/pyversions/knime-passbolt-py.svg)](https://pypi.org/project/knime-passbolt-py/)
[![License: Apache-2.0](https://img.shields.io/pypi/l/knime-passbolt-py.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![CI](https://github.com/DataNautics-GmbH/knime-passbolt-py/actions/workflows/ci.yml/badge.svg)](https://github.com/DataNautics-GmbH/knime-passbolt-py/actions/workflows/ci.yml)

Python wrapper for consuming Passbolt credentials in KNIME Python Script nodes,
via the **Credential to Python** bridge node shipped in the
[knime-passbolt](https://datanautics.net/passbolt) extension.

## Install

The package is distributed via **PyPI**. A conda-forge feedstock is planned
but not yet available — `mamba install knime-passbolt-py` / `conda install
knime-passbolt-py` will fail until then.

```bash
pip install knime-passbolt-py
```

Inside a conda or mamba environment, install with `pip` after ensuring `pip`
itself is present:

```bash
mamba install python=3.10 pip
pip install knime-passbolt-py
```

The package is pure-Python with no compiled dependencies, so a `pip` install
inside a conda env is safe.

## Usage

In a KNIME workflow, wire:

```
Passbolt Connector → Get Secret → Credential to Python → Python Script
```

In the Python Script node:

```python
import knime.scripting.io as knio
import requests

cred = knio.input_objects[0]            # PassboltSecret instance

with cred as c:                          # bytearray zeroed on __exit__
    h = c.basic_auth_header()
    resp = requests.get(url, headers={"Authorization": h.decode()})
```

## Security model

The credential lives in the **KNIME JVM**, in the existing in-memory
`CredentialCache` owned by the upstream Get Secret node. This wrapper carries
only a loopback broker URL (`http://127.0.0.1:<port>/v1/auth-header`) and a
short-lived bearer token. The Authorization header is fetched on demand,
held in a `bytearray`, and zeroed (`ctypes.memset`) when the `with` block
exits.

- `__slots__` prevents `__dict__` introspection.
- `__repr__` masks the broker URL only; never logs the token or any credential bytes.
- `__reduce__` re-pickles to the broker handshake — credential bytes are
  never serialized, even by accident.
- Broker URL is validated to be loopback at every fetch; tampering with a
  saved pickle to redirect to an external host is rejected client-side.

**Limits.** In-process Python code can read the bytearray while the `with`
block is open. CPython does not provide hardware-enforced isolation. The
posture is on par with KNIME's own *Credentials Configuration* flow variable
combined with a disciplined helper class — better is not achievable in
CPython without sandboxing.

### Supply-chain provenance

Releases are published to PyPI from GitHub Actions using **OIDC Trusted
Publishing** — no long-lived API token is stored anywhere. Each release also
ships PEP 740 attestations linking the artifacts to the exact workflow run that
built them. To report a vulnerability, see [`SECURITY.md`](./SECURITY.md).

## Compatibility

This package version (`0.1.1`) is compatible with the `knime-passbolt` KNIME extension version `0.1.1.20260520` and later. The full extension-↔-package compatibility matrix lives in [`CONTRACT.md`](./CONTRACT.md).

## Changelog

See [`CHANGELOG.md`](./CHANGELOG.md) for per-release notes, including the
security hardening recorded for each version.

## License

Apache 2.0. See the `LICENSE` file shipped with this package, or
<https://www.apache.org/licenses/LICENSE-2.0>.

## About

`knime-passbolt-py` is published by [Datanautics GmbH](https://datanautics.net/)
as the companion Python package for the `knime-passbolt` KNIME extension.

Source: <https://github.com/DataNautics-GmbH/knime-passbolt-py>
Issues: <https://github.com/DataNautics-GmbH/knime-passbolt-py/issues>
