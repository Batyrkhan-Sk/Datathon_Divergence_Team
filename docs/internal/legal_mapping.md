# Legal mapping (step 2)

Machine-readable version with verbatim quotes: [`data/rules.json`](../../data/rules.json).
The service must copy citations from that file and never generate them (criterion 4:
no invented references).

## Sources used (all RK, current as of 2026-10-17)

| Key | Act | Link |
|---|---|---|
| NB231 | Постановление Правления НБРК от 29.11.2019 № 231 — Правила осуществления кассовых операций и операций по инкассации… (last amended 30.06.2026 № 78) | https://adilet.zan.kz/rus/docs/V1900019680 |
| NB14 | Постановление Правления НБРК от 24.02.2020 № 14 — Правила организации охраны и устройства помещений банков… (last amended 24.12.2024 № 88; pp. 11, 13(3), 14, 16 run in a temporary wording until 01.01.2027) | https://adilet.zan.kz/rus/docs/V2000020075 |
| ARDFM53 | Постановление Правления АРРФР от 03.04.2026 № 53 — Требования к обеспечению информационной безопасности банков… (replaced НБРК № 48 of 2018) | https://adilet.zan.kz/rus/docs/V2600038336 |

Texts were read from the zakon.uchet.kz mirror of adilet (adilet.zan.kz is now a
JS app). Before submission, re-check each clause number directly on adilet.

## Type → rule

| Service type | Train videos | Key clause(s) | Strength |
|---|---|---|---|
| unauthorized_access (door left open / outsider enters) | X-4, X-30, X-38, X-18, X-33, X-32 | NB14 п.16(1), п.8, п.19(1) | direct |
| cash_unattended (teller leaves, cash on desk) | X-26, X-15, X-24 | NB231 п.20 ч.2, п.22 | direct |
| safe_left_open (open door, or key left in lock) | X-20, X-22, X-13? | NB231 п.20 ч.2, п.80 | interpretation |
| personal_items (coat, bag, food, drink, camera phone) | X-40, X-46 | NB231 п.12 | direct (items/phone), interpretation (food/drink) |
| no_machine_check (client cash counted by hand only) | X-47, X-1?, X-44? | NB231 п.19(2), п.41, п.9 | direct |
| client_absent (cash processed after client left) | X-34 | NB231 п.20 ч.1, п.31(4) | direct |
| collector_handover | X-17 | NB231 п.24(3–4), NB14 п.21 | uncertain mapping |
| workstation_unlocked | X-28, X-11 | ARDFM53 п.71(9) | **indirect — find better source** |
| no_client_identification (hypothesis) | X-2? | NB231 п.19(1), п.7 | direct norm, uncertain observation |

Ruled out: "door not locked when teller leaves" — clean X-29 shows the same door
behaviour on exit as X-24/X-11, and locking from outside is not visible.

## Notes
- NB231 п.12 also forbids bringing **camera-equipped phones** into the cash area — a
  likely unseen test type worth detecting cheaply (phone in teller's hands).
- NB231 п.42 (counting/sorting only in presence of a controlling employee) looked
  relevant to X-44, but clean X-43 shows the same lone counting, so it is **not**
  used — it would create false positives.
- Descriptions must state only what is visible (door open, person entered, cash on
  desk, screen on) and present the rule as "may indicate a violation of …", per case §7.

## TODO
- workstation_unlocked: look for a direct norm (bank secrecy — Закон «О банках и
  банковской деятельности», personal data — Закон «О персональных данных и их
  защите») and verify the exact article on adilet before citing.
- X-17, X-2: confirm what the violation is, then confirm the mapping.
