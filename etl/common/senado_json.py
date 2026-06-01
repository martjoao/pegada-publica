"""Helpers for the Senado API's verbose, XML-derived JSON.

The Senado open-data API serialises XML to JSON 1:1, which has two consequences
every consumer must handle:

- a single-child element is a **dict, not a one-element list** (``as_list``);
- payloads are deeply nested under a verbose envelope (``unwrap``).

These live in ``common`` so both the extract and transform stages share them.
"""
from __future__ import annotations

from typing import Any, List


def as_list(node: Any) -> List[Any]:
    """Coerce a Senado JSON node to a list (dict -> [dict], None -> [])."""
    if node is None:
        return []
    if isinstance(node, list):
        return node
    return [node]


def unwrap(payload: Any, *keys: str, default: Any = None) -> Any:
    """Dig through nested keys, returning ``default`` if any key is missing."""
    node = payload
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node
