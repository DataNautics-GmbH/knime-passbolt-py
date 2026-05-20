# Copyright (c) 2026 Datanautics GmbH
# SPDX-License-Identifier: Apache-2.0
"""Read a password-protected PDF using a Passbolt-stored password.

Use this as the body of a KNIME Python Script node wired downstream of:

    Passbolt Connector → Get Secret → Credential to Python

Plus an upstream File / Path Selector that emits the file path as the
``Location`` flow variable.

The Passbolt resource's *password* field holds the PDF password. The
*username* field is ignored.

Library installation, once per KNIME Python env::

    pip install pypdf

Path handling
-------------

KNIME's Python Script node has its CWD at the workspace root, not the
workflow data area, so relative paths emitted by a File Selector in
"Relative to: Workflow Data Area" mode (e.g. ``./secured file.pdf``)
do NOT resolve correctly with Python's standard CWD-based
``os.path.abspath``.

To handle this without forcing the workflow to switch to absolute paths,
:func:`resolve_file_path` falls back to searching the KNIME workspace
tree for the file's basename. Absolute paths are used as-is.

Output table::

    page | char_count | text
"""

import base64
import os
from pathlib import Path

import knime.scripting.io as knio
import pandas as pd
from pypdf import PdfReader

# Directory-name prefixes to prune during the workspace walk. Hidden dirs
# (.git, .metadata, .knime, …), Python build/cache dirs, and obvious temp
# locations are skipped — they never contain workflow roots.
_PRUNED_DIR_PREFIXES = (".", "node_modules", "__pycache__", "tmp", "temp")


def resolve_file_path(path_str: str) -> str:
    """Resolve ``path_str`` to an absolute, existing file path.

    Strategy:

    1. Absolute path → must exist as-is, else raise.
    2. Relative path & found at ``CWD/path`` → use that.
    3. Relative path → walk only the *category tree* of the KNIME
       workspace (``knime.workspace`` flow variable) looking for
       directories that contain a ``workflow.knime`` marker file. At
       each workflow root, probe ``<workflow>/data/<rel-path>`` once.
       The walk NEVER descends into a workflow's internals — those
       per-node subdirectories hold most of a workspace's directory
       entries and contribute zero useful candidates.

    KNIME's File Selector "Relative to: Workflow Data Area" emits paths
    like ``./foo.pdf`` where ``./`` is the workflow data area; the
    actual file therefore lives at ``<workflow>/data/foo.pdf``.
    """
    p = Path(path_str)

    if p.is_absolute():
        if not p.is_file():
            raise FileNotFoundError(f"File not found at {path_str!r}.")
        return str(p)

    cwd_resolved = p.resolve()
    if cwd_resolved.is_file():
        return str(cwd_resolved)

    workspace = knio.flow_variables.get("knime.workspace", "")
    if not workspace or not os.path.isdir(workspace):
        raise FileNotFoundError(
            f"Cannot resolve relative path {path_str!r}: workspace {workspace!r} not accessible."
        )

    # Strip the leading "./" — the relative path is relative to the data
    # area itself, so the file lives at `<workflow>/data/<this>`. Use
    # removeprefix (Py 3.9+) rather than lstrip — lstrip treats "./" as
    # a *set of characters* and would collapse "..foo.pdf" to "foo.pdf".
    target_rel = os.path.normpath(path_str).replace("\\", "/")
    for prefix in ("./", "../"):
        while target_rel.startswith(prefix):
            target_rel = target_rel[len(prefix) :]
    target_rel = target_rel.lstrip("/")
    target_parts = target_rel.split("/")

    workspace_norm = os.path.normpath(workspace)

    for root, dirs, files in os.walk(workspace_norm):
        if "workflow.knime" in files:
            # Workflow root — probe target and stop descending.
            candidate = os.path.join(root, "data", *target_parts)
            if os.path.isfile(candidate):
                return candidate
            dirs[:] = []  # never recurse into a workflow's node dirs
            continue
        # Non-workflow level — prune hidden / temp dirs and keep walking.
        dirs[:] = [d for d in dirs if not d.startswith(_PRUNED_DIR_PREFIXES)]

    raise FileNotFoundError(
        f"No file matching {path_str!r} found at <any-workflow>/data/"
        f"{target_rel!r} under workspace {workspace_norm!r}."
    )


cred = knio.input_objects[0]
pdf_path = resolve_file_path(knio.flow_variables["Location"])

with cred as c:
    # The wrapper currently exposes only the HTTP-Basic header form.
    # Decode the base64 to recover the password the PDF needs.
    header = c.basic_auth_header()
    _, b64 = header.split(b" ", 1)
    _user, _, password = base64.b64decode(b64).decode("utf-8").partition(":")

    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        # decrypt() returns: 0 = wrong password, 1 = user password, 2 = owner password
        result = reader.decrypt(password)
        if result == 0:
            raise ValueError(
                "Wrong password for PDF — the Passbolt resource's password "
                "field does not match the PDF's encryption password."
            )

    rows = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        rows.append(
            {
                "page": page_number,
                "char_count": len(text),
                "text": text,
            }
        )

knio.output_tables[0] = knio.Table.from_pandas(pd.DataFrame(rows))
