# Bridge contract

`knime-passbolt-py` and the [`knime-passbolt`](https://github.com/mikeg-de/knime-passbolt) KNIME extension communicate through a hand-crafted pickle byte stream emitted by the Java side and deserialised by `pickle.load` on the Python side. The byte format is a **stable contract** that both sides must honour.

## Pickle format (pickle protocol 2)

The emitter produces:

```
\x80 \x02                                  PROTO 2
c knime_passbolt \n _build_from_broker \n  GLOBAL → factory function
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → broker_url
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → token
X <4-byte LE len> <utf-8 bytes>            BINUNICODE → session_uuid
\x87                                       TUPLE3
R                                          REDUCE → call(*args)
.                                          STOP
```

## Function signature (Python side)

```python
def _build_from_broker(broker_url: str, token: str, session_uuid: str) -> PassboltSecret:
    ...
```

The module path is **`knime_passbolt._build_from_broker`**, not `knime_passbolt._secret._build_from_broker`. The `__init__.py` re-exports the function (with `# noqa: F401`) so the pickle `GLOBAL` opcode finds it at the canonical location.

## Trust boundary (READ THIS)

`pickle.load` on the Python side is **arbitrary-code-execution-capable by construction**. The Python wrapper validates its three string arguments (`_build_from_broker` → `PassboltSecret.__init__` → `_require_loopback`), but that validation only constrains the byte streams that *choose* to route through `_build_from_broker`. An attacker who can replace the pickle bytes simply emits a different `GLOBAL` opcode (e.g. `posix.system`) and ignores the factory entirely.

The whole security model therefore rests on a single assumption:

> **The pickle byte stream is only ever written to trusted storage.** The bytes are *not* transit-only: `CredentialToPythonNodeModel.execute()` persists them to a FileStore file on disk on every execute (`PickledObjectFileStorePortObject`). The trust boundary is the **KNIME workflow / FileStore directory** — anyone with write access to it can already edit the Python Script node's own source (arbitrary Python, executed verbatim), so the pickle adds no attack surface beyond what KNIME already exposes.

**Status: accepted (resolved 2026-06-28).** Restricting the unpickler is not an option this extension controls — `pickle.load` runs in KNIME's `_knime_scripting_launcher.py`, not our code — and a MAC the factory checks is dead weight because the attacker bypasses the factory entirely. The reasoning is recorded in the `knime-passbolt` extension's security model (`docs/SECURITY.md` → "Python bridge: pickle trust boundary (accepted assumption)").

Two consequences:

1. **If a future deployment routes these bytes outside the workflow/FileStore directory** (unauthenticated network transit, shared temp, an export path), the accepted assumption is violated — escalate to the KNIME platform team to restrict the unpickler at the platform level (`find_class` allow-list limited to `knime_passbolt._build_from_broker`).
2. **The `token` in the pickle bytes is a live bearer credential** for the loopback broker (replayable until the bridge node's `reset()` / `onDispose()` revokes it). `PassboltSecret.__reduce__` re-emits it on `pickle.dumps`, so any re-pickling of the wrapper writes a live loopback credential — keep it inside the same trusted boundary. No Passbolt password or PGP material is ever in the pickle.

## Compatibility matrix

| Extension version | knime-passbolt-py version | Broker URL | Argument order |
|---|---|---|---|
| `0.1.1.20260520+` | `0.1.0+` | `http://127.0.0.1:<port>/v1/auth-header` | `(broker_url, token, session_uuid)` |

A new entry is added here on every change to the byte format, the function signature, the URL path, or the broker response shape.

## How to change the contract safely

1. **Additive changes only across one minor version.** Adding a 4th argument to `_build_from_broker` requires releasing the Python side first (accepts the new arg with a default) before the Java side starts emitting it.
2. **Breaking changes require a major bump on BOTH sides simultaneously**, plus an updated row in the matrix.
3. **Test cross-version compatibility** — run the latest Python-side wrapper against the previous Java-side emitter and vice versa before tagging.

## Producer and consumer source locations

- **Producer (Java):** `org.knime.ext.passbolt.python.PythonPickleEmitter` in `mikeg-de/knime-passbolt`.
- **Consumer (Python):** `_build_from_broker(broker_url, token, session_uuid)` in `src/knime_passbolt/_secret.py` (re-exported by `src/knime_passbolt/__init__.py`).

## Where to file bugs

- **Broker / JVM-side issues:** [`mikeg-de/knime-passbolt`](https://github.com/mikeg-de/knime-passbolt) issue tracker.
- **`PassboltSecret` / Python-wrapper issues:** this repo's issue tracker.
- **Cross-repo issues** (contract drift, version-pair mismatch): file in both, cross-link, tag `cross-repo`.
