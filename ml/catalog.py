"""Violation-type catalogue and legal citations, loaded from data/rules.json.

Citations are only ever copied from this file, never generated.
"""
import json
from functools import lru_cache
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "data" / "rules.json"


@lru_cache(maxsize=4)
def load(path: str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_RULES
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. rules.json is not in git; get it from the team share."
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        "documents": data["_meta"]["documents"],
        "types": {t["id"]: t for t in data["types"]},
    }


def type_name(type_id: str, rules_path: str | None = None) -> str:
    t = load(rules_path)["types"].get(type_id)
    return t["name"] if t else "Иное возможное нарушение"


def citation(type_id: str, rules_path: str | None = None) -> dict | None:
    """Primary rule for a type: {document, clause, quote, url}."""
    cat = load(rules_path)
    t = cat["types"].get(type_id)
    if not t or not t["sources"]:
        return None
    src = t["sources"][0]
    doc = cat["documents"][src["doc"]]
    return {
        "document": f'{doc["title"]} ({doc["act"]})',
        "short": doc.get("short", doc["title"]),
        "clause": src["clause"],
        "quote": src["quote"],
        "url": doc["url"],
    }
