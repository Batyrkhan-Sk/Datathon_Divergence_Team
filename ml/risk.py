"""Assign a risk_level to each detected violation based on its type_id."""

RISK_MAP = {
    # High: direct cash exposure or third-party access
    "unauthorized_access": "high",
    "safe_left_open": "high",
    "collector_handover": "high",
    "cash_unattended": "high",
    # Medium: process / security policy violations
    "workstation_unlocked": "medium",
    "no_client_identification": "medium",
    "client_absent": "medium",
    "no_machine_check": "medium",
    # Low: minor policy
    "personal_items": "low",
    # Camera integrity
    "camera_tamper": "high",
}

RISK_LABELS = {
    "high": "Высокий риск",
    "medium": "Средний риск",
    "low": "Низкий риск",
}


def add_risk(result: dict) -> None:
    """Mutates violations in-place: adds risk_level string."""
    for v in result.get("violations") or []:
        tid = v.get("type_id", "")
        v["risk_level"] = RISK_MAP.get(tid, "medium")
