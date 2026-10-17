# Frontend

Web UI for uploading a teller-workplace video and reviewing possible
cash-discipline violations. Plain HTML/CSS/JS: no build step, no frameworks, and no
external resources (no CDNs or web fonts), so it works offline. The backend serves
this folder as static files at `/`.

## Structure

| File | Purpose |
|---|---|
| `index.html` | Page markup. Four views: upload, processing, error/timeout, result. Also holds the frame lightbox (`<dialog>`) |
| `styles.css` | Styles. Responsive down to 375 px; two columns (player and findings) from 960 px |
| `format.js` | Pure helpers: timecode `мм:сс.с`, sizes, file validation, result normalisation. Also loads in node for tests |
| `api.js` | API client (XHR upload with progress, `fetch` polling) and the mock client |
| `app.js` | UI controller: drag and drop, status, polling with backoff and timeout, result rendering, player and timeline, lightbox |
| `mock/result.json` | Mock `done` job with 2 violations (real X-26 frames, downscaled) |
| `mock/result_clean.json` | Mock `no_violation` job |

## Run

**Mock mode** (no backend needed; any static server works):

```bash
.venv/Scripts/python -m http.server 8090 --directory frontend
# http://127.0.0.1:8090/?mock=1        -> 2 violations
# http://127.0.0.1:8090/?mock=clean    -> no violation
# http://127.0.0.1:8090/?mock=fail     -> failed job
# http://127.0.0.1:8090/?mock=timeout  -> timeout screen (shortened to 8 s)
# http://127.0.0.1:8090/?mock=noprogress -> processing without a progress value
```

In mock mode you still pick a real video. It plays locally, and the result comes
from `mock/*.json`. Opening `index.html` as `file://` does not work, because the mock
JSON is loaded with `fetch`.

Test hook (mock mode only): `?mock=1&auto=1&video=<url>` starts the flow with no
file picker. This is used for headless screenshots.

**With the backend:** open the backend root (`/`). The UI calls the same origin.

## API used

| Call | Details |
|---|---|
| `POST /ui/api/analyze` | multipart, field `file`. Reads `job_id`. On an error, shows `detail` or `error` |
| `GET /ui/api/jobs/{job_id}` | Polled every 2 s. Network errors and 5xx/408/429 are retried with backoff up to 15 s; other 4xx stop. Polling stops after 6 minutes, and the timeout screen offers to keep waiting, upload again or start over |

**Fields read:** `status` (`processing`/`done`/`failed`), `progress` (0–1, optional;
without it the bar is indeterminate), `error`, `verdict`, `processing_sec`, and for each
violation: `type`, `timecode_sec`, `description`, `confidence`, `rule {document, clause,
quote, url}` and `evidence_frames[] {timestamp_sec, image_base64}`.

Only `status`, `verdict` and `violations` are required. Everything else may be missing,
and `rule` may be `null`. `image_base64` is a raw base64 JPEG; a full `data:` URI is also
accepted. Only `http(s)` links are rendered.

The video is never sent back by the server. The player uses `URL.createObjectURL` on the
user's file. If the browser cannot decode it, the player is hidden and the evidence
frames remain.

## Tests

`format.js` can be loaded in node with `require('./format.js')`. All API strings are put
into the DOM with `textContent`, never with `innerHTML`.
