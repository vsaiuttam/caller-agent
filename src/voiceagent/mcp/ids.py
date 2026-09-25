"""Server slugs and tool ids.

A tool id is the name the model calls a tool by, so it has to satisfy both
providers' rule, `^[a-zA-Z0-9_-]{1,64}$`, and be unambiguous across every
server a campaign uses — two apps can both offer `search`. Prefixing the
server's slug does both, and it is also what campaigns store, which is why a
slug never changes once it is made.
"""

from __future__ import annotations

import hashlib
import re

SLUG_MAX = 32
TOOL_ID_MAX = 64
# Slugs never contain a double underscore (runs collapse to one), so this
# separator splits an id back into its server and tool unambiguously.
SEPARATOR = "__"


def slugify(name: str) -> str:
    """Lowercase `[a-z0-9_]`, from a server's display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:SLUG_MAX].strip("_")
    # A name in Devanagari leaves nothing behind; the id still needs a stem.
    return slug or "server"


def unique_slug(name: str, taken: set[str]) -> str:
    """`slugify(name)`, with `_2`, `_3`… appended until it is not in `taken`."""
    base = slugify(name)
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"_{number}"
        candidate = base[: SLUG_MAX - len(suffix)].rstrip("_") + suffix
        if candidate not in taken:
            return candidate
        number += 1


def server_prefix(slug: str) -> str:
    """What every tool id from the server with this slug starts with."""
    return f"{slug}{SEPARATOR}"


def tool_id(slug: str, tool_name: str) -> str:
    """The id a campaign and the model use for one server's tool.

    Over-long ids are cut and given a short hash of the full tool name, so two
    long names that share a prefix still get different ids.
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name) or "tool"
    full = f"{server_prefix(slug)}{safe}"
    if len(full) <= TOOL_ID_MAX:
        return full
    digest = hashlib.sha256(tool_name.encode()).hexdigest()[:8]
    return f"{full[: TOOL_ID_MAX - len(digest) - 1]}_{digest}"
