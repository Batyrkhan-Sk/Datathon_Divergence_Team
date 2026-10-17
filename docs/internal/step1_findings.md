# Step 1 — violation taxonomy (draft)

Source: contact sheets in `out/sheets/` (overview / ±4s window / desk close-up) and
zooms in `out/zoom/`. Regenerate with `tools/contact_sheets.py` and `tools/zoom.py`.

## Dataset facts
- 42 videos, all 464x848 portrait, ~30 fps, 11–143 s. 22 violation / 20 clean.
- Labels mix Latin `X` and Cyrillic `Х`; copies in `data/raw/` are normalised to Latin.
- **At least 3 room layouts / camera positions** already in train (desk+safe on the right
  with client chair; desk rotated with safe behind; desk with blue chair). Expect
  more in test.
- Label timestamp ≈ the moment the violation *becomes visible* (person enters, teller
  stands up to leave, safe left open), not the end of the action.

## Candidate types

| # | Type (working name) | Videos (label t) | Visual signature | Clean counter-example | Confidence |
|---|---|---|---|---|---|
| A | Outsider in cash area while cash/valuables exposed | X-4 (57), X-30 (13), X-38 (33), X-18 (20) | Person enters through door / approaches teller side while banknotes lie on desk; X-18: teller hands item to a 3rd person | X-3: client enters, sits, normal service | medium — need to separate "client" from "outsider" |
| B | Valuables handed over / accepted irregularly with collector | X-17 (7) | Cash collector enters with green cash bag, places it on desk, teller takes it | — | low |
| C | Teller leaves workplace with valuables unattended | X-26 (9), X-15 (15), X-11 (18), X-24 (8) | Teller stands up / walks out door while cash (X-26) or cash bag (X-15) remain on desk; X-11 lights go off | X-29: leaves with empty desk | high for X-26/X-15 |
| D | Workstation not locked on leaving | X-28 (7) | Teller leaves, laptop still shows spreadsheet | X-29: laptop shows lock screen before she leaves | high |
| E | Safe left open / not secured | X-20 (5), X-13 (47), X-22 (14)? | Safe door stays open while teller works away from it; X-22 possibly key left in safe | X-21: takes cash and closes safe | high for X-20, low for X-22 |
| F | Personal belongings at cash workplace | X-40 (17) | Coat and handbag placed on the cash desk | — | high |
| G | Eating / drinking at cash workplace | X-46 (11) | Teller drinks from cup with cash on desk | — | high |
| H | Cash accepted/counted without counting machine | X-47 (68), X-1 (22)?, X-44 (16)? | Client's bundle counted by hand only, machine next to teller unused | X-43: hand count *after* machine count | medium |
| I | Cash-room door not secured after teller enters | X-33 (6), X-32 (5) | Teller enters and walks to desk without any locking action at the door; X-33: at 10–13s an outsider opens the door and looks in while she feeds the counting machine | — | high for X-33 (outsider visible), medium for X-32 (only the omission is visible) |
| J | Client's cash processed after the client has left | X-34 (13) | Client stands up and walks out; teller then feeds cash into the counting machine with nobody across the desk | X-3: machine count while client is seated | medium |
| ? | Unresolved | X-2 (10) | Client sits, puts a small blue item on desk; teller picks it up, examines it, reaches to counting machine | — | hard to tell (human review too) |

## Open questions — watch these in a player
- X-2 @10s: still unknown after human review.
- X-1 @22s vs X-44 @16s vs clean X-43: what differs in the cash handling?
- X-22 @14s: is a key left in the safe?
- X-17 @7s: is the collector entering the cash room itself the violation?
- X-24 @8s: drink can + tablet on desk, or leaving unlocked?

## Omission types (I, J): what we can and cannot claim
"Door not locked" is not directly visible — a lock turn is a few pixels at best.
Per case §7 the service must not assert invisible facts. Phrase evidence as what is
seen: "teller entered and did not close/secure the door behind her" and, when
present, "another person opened the door at T while cash operations were in
progress". The second event is the strongest evidence frame; the label timecode
sits on the entry (the moment of omission), so report the entry time as
`timecode_sec` and include the intrusion frame as an extra evidence frame.

## Early design implications
- Most types are **object/state + person-presence rules**: cash on desk, safe door
  open, laptop screen state, person count/zone, teller absent. A detector +
  tracker + per-frame state machine covers A, C, D, E; F and G need open-vocabulary
  detection (coat/bag, cup) or a VLM check.
- Several layouts in train ⇒ zones must be inferred per video (detect desk/safe/door),
  not hard-coded.
- Banknotes are small (≈20–40 px) at native resolution — "cash on desk" needs crops
  or a VLM on the desk region.
