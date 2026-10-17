"""Violation-type catalogue and legal citations, loaded from data/rules.json.

Citations are only ever copied from this file, never generated.
"""
import json
import re
import urllib.parse
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


FRAGMENT_WORDS = 8


def deep_link(url: str, quote: str) -> str:
    """Link that opens the act at the quoted clause: a text fragment (#:~:text=...) makes
    Chrome, Edge, Safari and Firefox scroll to and highlight the first words of the quote;
    other browsers just open the act. adilet has no stable per-clause URLs."""
    text = re.sub(r"[«»\"…]|\.\.\.", " ", quote or "")
    # A fragment cannot span list items (sub-points end with ";"): keep the first one.
    first = text.split(";")[0]
    words = (first if len(first.split()) >= 3 else text).split()[:FRAGMENT_WORDS]
    if not url or len(words) < 3:
        return url
    return url + "#:~:text=" + urllib.parse.quote(" ".join(words), safe="")


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
        "url": deep_link(doc["url"], src["quote"]),
    }
