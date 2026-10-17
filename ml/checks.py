"""What the service checked in this video, per violation type: found / not found / could
not be checked (with the reason). Lets the reviewer see the coverage of a clean result and
the limits on an unfamiliar camera angle. Built only from facts the detectors computed."""
import os

from .events import Event

FOUND, CLEAR, NOT_CHECKED = "found", "clear", "not_checked"

# Short names for the checklist (the full type names stay in violations).
LABELS = {
    "unauthorized_access": "Посторонние в кассовой зоне",
    "cash_unattended": "Наличные без присмотра",
    "workstation_unlocked": "Экран не заблокирован при уходе",
    "safe_left_open": "Сейф оставлен открытым",
    "personal_items": "Личные вещи, еда и напитки",
    "collector_handover": "Инкассаторская сумка на столе",
}
# Types in the catalogue that need a person to watch the recording.
MANUAL = {
    "no_machine_check": "пересчёт без счётной машинки",
    "client_absent": "операции в отсутствие клиента",
    "no_client_identification": "идентификация клиента",
}


def build(ctx, events: list[Event]) -> dict:
    ex = ctx.extras
    vlm_on = os.environ.get("ML_USE_VLM") == "1"
    present = sum(1 for p in ex.get("people") or [] if p)
    workplace, laptop = ex.get("workplace"), ex.get("laptop")
    departures = ex.get("departures")  # set by the workplace detector
    from .detectors.personal_items import _desk_crop_box
    desk = _desk_crop_box(ctx) is not None

    def stay(note):  # departure-based checks: nothing to see if the teller never left
        return (CLEAR, note) if departures else (CLEAR, "кассир не оставлял помещение пустым")

    status = {}
    status["unauthorized_access"] = ((CLEAR, None) if present else
                                     (NOT_CHECKED, "люди в кадре не найдены"))
    if workplace is None:
        status["cash_unattended"] = (NOT_CHECKED, "рабочее место не найдено в кадре")
    else:
        status["cash_unattended"] = stay(
            None if laptop is not None else "рабочее место определено по положению кассира")
    status["workstation_unlocked"] = ((NOT_CHECKED, "ноутбук не виден в кадре") if laptop is None
                                      else stay(None))
    if not vlm_on:
        status["safe_left_open"] = (NOT_CHECKED, "проверка сейфа отключена")
    elif not ex.get("safe"):
        status["safe_left_open"] = (NOT_CHECKED, "сейф не найден в кадре")
    else:
        status["safe_left_open"] = (CLEAR, None)
    status["personal_items"] = ((CLEAR, None) if vlm_on and desk else
                                (CLEAR, "проверены только чашки и бутылки"))
    status["collector_handover"] = ((CLEAR, None) if vlm_on and desk else
                                    (NOT_CHECKED, "зона стола не найдена"))

    first = {}
    for e in sorted(events, key=lambda e: e.t_start):
        first.setdefault(e.type_id, e.t_start)
    items = []
    for type_id, label in LABELS.items():
        st, note = status[type_id]
        item = {"type_id": type_id, "label": label, "status": st, "note": note}
        if type_id in first:
            item.update(status=FOUND, note=None, timecode_sec=round(first[type_id], 2))
        items.append(item)
    order = {FOUND: 0, CLEAR: 1, NOT_CHECKED: 2}
    items.sort(key=lambda i: order[i["status"]])
    return {"items": items, "manual": list(MANUAL.values())}
