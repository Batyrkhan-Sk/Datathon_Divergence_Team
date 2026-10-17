# Datathon 26 — Полный статус проекта

*Обновлено: 2026-10-18. Всё в одном файле: статус, архитектура, типы нарушений, нормативная база, результаты feasibility, план.*

---

## 1. Что сделано / что не сделано

### ✅ Готово

| Область | Результат |
|---|---|
| **Бэкенд** | FastAPI, jury API (`POST /api/v1/analyze`, `GET /api/v1/jobs/{id}`, `X-API-Key → 401`), keyless UI API с rate-limit, один worker-процесс + очередь + таймаут 240 с + авторестарт, SQLite-хранилище, нормализация ответа (verdict ↔ violations, 1–3 JPEG гарантированы). 27/27 тестов, jury contract checker PASS (включая 5 параллельных загрузок) |
| **Фронтенд** | HTML/CSS/JS без сборки, оффлайн. Upload с drag-and-drop, прогресс, polling, вердикт-баннер, карточки нарушений (тип, таймкод, описание, ссылка adilet, кадры с лайтбоксом), видеоплеер с timeline-маркерами, mock-режим `?mock=1/clean/fail/timeout`. Добавлен scene view и checklist |
| **Нормативная база** | `data/rules.json`: 9 типов нарушений, 3 акта РК (НБРК № 231, НБРК № 14, АРРФР № 53), дословные цитаты. `catalog.py` — citations только из файла, pipeline никогда не генерирует юртекст |
| **Разметка** | 42 видео: 22 нарушения, 20 чистых. `data/labels.csv`: вердикт, таймкод, тип (18/22 определены), раскладка помещения A–E |
| **Eval-харнесс** | `eval/run_eval.py`: метрики по всем 42 видео, по раскладкам, по видео. `eval/cache_detections.py` — кэш RT-DETR для быстрого прогона |
| **Feasibility** | RT-DETR v2 R18 — выбран (0.16 с/кадр, 0.18 GB). OWLv2 — для кропов. GDINO — отклонён. VLM — Qwen3-VL-2B в 4-bit (~1.6 GB) |
| **Инструменты** | `tools/extract_frames.py`, `tools/contact_sheets.py`, `tools/zoom.py`, `tools/augment_videos.py` |
| **Деплой** | `deploy/run_server.sh`, `run_tunnel.sh`, `run_ngrok.sh`, `watchdog.sh` |
| **Документация** | `docs/SUBMISSION.md` — полный пакет сдачи |

### ✅ Детекторы (4 из 9 типов реализованы)

| Детектор | Тип нарушения | Покрывает видео | Метод |
|---|---|---|---|
| `workplace.py` | `cash_unattended` | X-26, X-15, X-24 | Уход кассира → OWLv2 ищет наличные на столе |
| `workplace.py` | `workstation_unlocked` | X-28, X-11 | Уход кассира → яркость/синева экрана ноутбука |
| `crowd.py` | `unauthorized_access` | X-4, X-30, X-38, X-18, X-33, X-32 | ≥3 человек ≥5 с; или 2-й человек входит в кабинет-одиночку |
| `safe.py` | `safe_left_open` | X-20, X-22 | VLM локализует сейф → yes/no вопросы на кропе (только при `ML_USE_VLM=1`) |
| `personal_items.py` | `personal_items` + `collector_handover` | X-40, X-46, X-17 | RT-DETR cup/bottle + VLM вопрос о пальто/сумке на столе |

### ❌ Детекторы не реализованы (5 из 9 типов)

| Тип | Видео | Сложность |
|---|---|---|
| `no_machine_check` | X-47, X-1?, X-44? | Высокая — нужно видеть счётную машинку + ручной счёт |
| `client_absent` | X-34 | Средняя — уход клиента → продолжение операции |
| `no_client_identification` | X-2? | Низкая уверенность — гипотеза |

### ❌ Остальное

| Область | Статус |
|---|---|
| **RAM** | `list(iter_frames(...))` = ~670 MB для 143-с видео (SAMPLE_FPS снижен до 2.0, но всё ещё много) |
| **Публичный URL** | Скрипты деплоя есть, но туннель не запущен |
| **`.env`** | `API_KEY` не задан — нужно создать перед сдачей |
| **VLM-тест** | Qwen3-VL-2B выбран, но точность на всём датасете не измерена |

---

## 2. Архитектура

```
frontend/   HTML/CSS/JS, без сборки. Бэкенд отдаёт на /
            /ui/api/* — keyless, rate-limited
            URL.createObjectURL — видео играет локально

backend/    FastAPI. Два API:
            /api/v1/*  — jury, X-API-Key обязателен
            /ui/api/* — UI, без ключа, per-IP rate limit
            Один worker-процесс, очередь, SQLite в backend/storage/
            app/results.py — нормализация вывода

ml/
  pipeline.py       analyze(path) → dict; perceive() → ctx.extras; warmup()
  scene.py          people_in_room, laptop_box, teller_anchor, departures, sustained
  checks.py         coverage checklist (что проверено / не найдено / недоступно)
  events.py         Event dataclass
  evidence.py       JPEG + боксы, base64
  catalog.py        читает data/rules.json
  video.py          cv2 декодирование, точные timestamps
  perception/
    objects.py      RT-DETR v2 R18 — люди, ноутбук, чашки, телефон (COCO)
    zeroshot.py     OWLv2 — поиск наличных/монет/сумки на кропе стола
    vlm.py          Qwen3-VL-2B/8B — yes/no вопросы + locate() + describe()
  detectors/
    crowd.py        → unauthorized_access
    workplace.py    → cash_unattended + workstation_unlocked
    safe.py         → safe_left_open  (только ML_USE_VLM=1)
    personal_items.py → personal_items + collector_handover
```

### Поток пайплайна

```
.mov
 ├─ iter_frames(2 fps) → ctx.frames
 ├─ perceive():
 │   ├─ objects.detect()   → ctx.extras["objects"], ["people"]
 │   ├─ scene.laptop_box() → ctx.extras["laptop"]
 │   └─ scene.teller_anchor() → ctx.extras["workplace"] (fallback)
 └─ каждый детектор(ctx) → list[Event]
     └─ _merge() → violations → JSON
```

### Контракт ML → Бэкенд

```python
from ml.pipeline import analyze
result = analyze("video.mov", progress=lambda p: ...)
# {
#   "verdict": "violation" | "no_violation",
#   "violations": [{
#     "type": str,              # из rules.json
#     "type_id": str,           # e.g. "cash_unattended"
#     "timecode_sec": float,
#     "confidence": float,
#     "description": str,       # наблюдение + "Возможное нарушение: …"
#     "rule": {"document", "clause", "quote", "url"},
#     "evidence_frames": [{"timestamp_sec", "image_base64"}]
#   }],
#   "processing_sec": float,
#   "scene": {"timestamp_sec", "image_base64", "objects": [...]},  # опционально
#   "checks": {"items": [...], "manual": [...]}                     # опционально
# }
```

### Добавление детектора

1. Создать `ml/detectors/<type_id>.py`
2. Декорировать функцию `@register("<type_id>")`
3. Импортировать в `ml/detectors/__init__.py`
4. `type_id` должен быть в `data/rules.json`

`ctx.frames` — список `(t_sec, BGR frame)` при 2 fps.
`ctx.extras` заполнен `perceive()`: `times`, `objects`, `people`, `laptop`, `workplace`.
`Event` нужен: `type_id`, `t_start`, `confidence`, `observation`.

---

## 3. Типы нарушений

### Приоритет 🔴 (6+ видео или высокая сигнатура)

#### `unauthorized_access` — Посторонний в зоне кассовых операций
- **Обучающие:** X-4@57, X-30@13, X-38@33, X-18@20, X-33@6, X-32@5
- **Видимое:** Дверь не закрыта после входа кассира И/ИЛИ в помещение входит иное лицо, пока на столе наличные
- **Норма:** НБРК № 14, п. 16 подп. 1) — «каждая касса имеет отдельный вход с закрывающейся на замок дверью»
- **Confidence:** direct

#### `cash_unattended` — Наличные оставлены без присмотра
- **Обучающие:** X-26@9, X-15@15, X-24@8
- **Видимое:** Кассир уходит, на столе остаются банкноты или инкассаторская сумка
- **Норма:** НБРК № 231, п. 22 — «кассовому работнику не допускается покидать рабочее место до окончания обслуживания клиента»
- **Confidence:** direct

#### `safe_left_open` — Сейф не закрыт или ключ в замке
- **Обучающие:** X-20@5, X-22@14, (X-13@47 под вопросом)
- **Видимое:** Дверца сейфа открыта пока кассир отходит (X-20); ключ оставлен в замке (X-22)
- **Норма:** НБРК № 231, п. 20 ч. 2 — хранение в закрывающемся на ключ устройстве
- **Confidence:** interpretation

### Приоритет 🟡 (2–3 видео)

#### `workstation_unlocked` — Рабочая станция не заблокирована
- **Обучающие:** X-28@7, X-11@18
- **Видимое:** Кассир уходит, экран ноутбука показывает рабочее приложение (в чистом X-29 перед уходом видна заставка блокировки)
- **Норма:** АРРФР № 53, п. 71 подп. 9) — автоблокировка (КОСВЕННАЯ; нужен прямой источник)
- **Confidence:** indirect

#### `personal_items` — Личные вещи / еда / напитки в кассе
- **Обучающие:** X-40@17 (пальто и сумка на столе), X-46@11 (пьёт из кружки)
- **Видимое:** Одежда, сумка, еда, напитки на кассовом столе; смартфон с камерой
- **Норма:** НБРК № 231, п. 12 — «хранение личных вещей … вне кассового узла»
- **Confidence:** direct (одежда/сумка/телефон), interpretation (еда/напитки)

#### `no_machine_check` — Наличные приняты без счётного оборудования
- **Обучающие:** X-47@68, (X-1@22?, X-44@16? под вопросом)
- **Видимое:** Кассир считает вручную, счётчик рядом не используется
- **Норма:** НБРК № 231, п. 41 — «банки осуществляют кассовые операции … на оборудовании»
- **Confidence:** direct

### Приоритет 🟢 (1 видео или гипотеза)

#### `client_absent` — Пересчёт без клиента
- **Обучающие:** X-34@13
- **Видимое:** Клиент уходит, кассир продолжает считать наличные
- **Норма:** НБРК № 231, п. 20 ч. 1 — «принимаются и пересчитываются в присутствии клиента»
- **Confidence:** direct

#### `collector_handover` — Приём инкассаторской сумки без проверки
- **Обучающие:** X-17@7 (под вопросом)
- **Видимое:** Инкассатор передаёт сумку без видимого осмотра целостности/пломбы
- **Норма:** НБРК № 231, п. 24 подп. 3)–4)
- **Confidence:** uncertain mapping

#### `no_client_identification` — Приём без идентификации
- **Обучающие:** X-2@10 (гипотеза)
- **Видимое:** Клиент кладёт наличные, не показывая документ
- **Норма:** НБРК № 231, п. 19 подп. 1)
- **Confidence:** direct norm, uncertain observation

---

## 4. Нормативные источники

| Ключ | Акт | Ссылка |
|---|---|---|
| NB231 | Постановление Правления НБРК от 29.11.2019 № 231 (ред. 30.06.2026 № 78) — Правила кассовых операций и инкассации | https://adilet.zan.kz/rus/docs/V1900019680 |
| NB14 | Постановление Правления НБРК от 24.02.2020 № 14 (ред. 24.12.2024 № 88) — Правила организации охраны и устройства помещений | https://adilet.zan.kz/rus/docs/V2000020075 |
| ARDFM53 | Постановление Правления АРРФР от 03.04.2026 № 53 — Требования к информационной безопасности банков | https://adilet.zan.kz/rus/docs/V2600038336 |

**Исключены:** «дверь не заперта при уходе» — чистый X-29 показывает то же поведение; «волосы распущены» — чистый X-43 тоже.

**TODO:** найти прямой источник для `workstation_unlocked` (банковская тайна / персональные данные РК); перепроверить все номера статей на adilet.zan.kz перед сдачей.

---

## 5. Датасет

- 42 видео: 22 нарушения, 20 чистых
- Формат: .mov, 464×848, ~30 fps, 11–143 с, без звука
- **5 раскладок** помещения (A–E) уже в train; тестовое — другой угол
- `data/labels.csv`: вердикт, таймкод, тип нарушения, раскладка (A–E)
- `data/open_labels.xlsx`: исходные метки организаторов
- Нерешённые: X-1, X-2, X-13, X-17, X-44

**Не в git:** `data/raw/X-*.mov`, `data/frames/` (кэш 4 fps)

---

## 6. Результаты feasibility (RTX 3050 Laptop, 4 GB)

| Модель | Лицензия | с/кадр | GPU | Вердикт |
|---|---|---|---|---|
| **RT-DETR v2 R18** | Apache-2.0 | 0.16 | 0.18 GB | ✅ Люди и ноутбуки |
| OWLv2 base | Apache-2.0 | 0.58 | 0.39 GB | ✅ Сцена (1 раз на видео) |
| Grounding DINO tiny | Apache-2.0 | 7.08 | 1.93 GB | ❌ Слишком медленный |

**Что видит RT-DETR:** люди (0.88–0.93), ноутбуки (0.9+), счётная машинка как «handbag» (0.5–0.65).  
**Не видит никто:** сейф, банкноты, ключ в замке → нужен VLM на кропах или fine-tune.

**Подводный камень:** люди и экраны отражаются в стеклянных стенах → фильтровать score ≥ 0.75 + ноги на полу внутри комнаты.

**VLM-тест:** ещё выполняется. Кандидаты: Qwen3-VL-2B, SmolVLM2-2.2B, Moondream2, Florence-2.

### Запрещённые модели
- Ultralytics YOLOv5/v8/v11 — AGPL-3.0
- Qwen2.5-VL-3B — research licence
- Любые cloud API — дисквалификация

---

## 7. Рекомендуемый стек моделей

| Задача | Выбор | Лицензия |
|---|---|---|
| Люди + ноутбук | RT-DETR v2 R18 | Apache-2.0 |
| Трекинг (кассир vs клиент) | ByteTrack | MIT |
| Поза рук | RTMPose-s | Apache-2.0 |
| Сцена zero-shot (сейф, дверь, сумка, кружка) | OWLv2 | Apache-2.0 |
| Состояние сейфа/экрана/наличных | MobileNetV3 на кропах | BSD-3 |
| Верификация кандидатов / новые типы | Qwen3-VL-2B или SmolVLM2 | Apache-2.0/MIT |
| Fine-tune (если нужно) | RT-DETR v2 R18 или D-FINE-S | Apache-2.0 |

**Принцип:** не обучать end-to-end видео-модель на 42 клипах; fine-tune только мелкие части (кассовые объекты, классификаторы состояний).

---

## 8. Команды

```bash
# Установка (Python 3.11)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r backend/requirements.txt
.venv/Scripts/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv/Scripts/python -m pip install -r requirements-ml.txt

# Запуск бэкенда (нужен .env с API_KEY=...)
python -m backend

# Фронтенд в mock-режиме (без бэкенда)
python -m http.server 8090 --directory frontend
# → http://127.0.0.1:8090/?mock=1

# Анализ одного видео
python -m ml.pipeline data/raw/X-26.mov

# Тесты бэкенда (~1 мин, нужны X-26.mov и X-29.mov)
.venv/Scripts/python -m pytest backend/tests -v

# Проверка jury-контракта
python backend/check_api_contract.py --base-url http://localhost:8000 --key $KEY \
    --video data/raw/X-26.mov --concurrent 5

# Оценка пайплайна
python -m eval.run_eval --tag my-change
# подмножество: --layouts D E   или   --videos X-26 X-29

# Кэш кадров 4 fps (один раз)
python tools/extract_frames.py data/raw data/frames 4

# Контактные листы всех видео → out/sheets/
python tools/contact_sheets.py data/raw data/open_labels.xlsx out/sheets

# Zoom на сегмент (video t0 t1 step x0 y0 x1 y1 out.jpg)
python tools/zoom.py data/raw/X-1.mov 19 24 0.5 0 0.3 0.7 0.6 out/zoom/X-1.jpg
```

---

## 9. Env-переменные (.env в корне репо)

### Бэкенд
| Переменная | Умолч. | Описание |
|---|---|---|
| `API_KEY` | (нет) | Обязателен для `/api/v1/*`; без него — 401 |
| `ANALYZER` | `real` | `demo` — фейковые нарушения с реальными кадрами (для UI) |
| `JOB_TIMEOUT_SEC` | `240` | Жёсткий лимит на задание |
| `LOAD_TIMEOUT_SEC` | `600` | Лимит загрузки моделей |
| `STRICT_SCHEMA` | `0` | `1` — только документированные поля в ответе |
| `STORAGE_DIR` | `backend/storage` | SQLite + загруженные файлы |
| `MAX_UPLOAD_MB` | `300` | Лимит файла |

### ML-модели
| Переменная | Умолч. | Описание |
|---|---|---|
| `ML_USE_VLM` | `0` | `1` — включить Qwen3-VL (нужен для safe, belongings, cup-verify) |
| `ML_IGNORE_LAPTOP` | `0` | `1` — симулировать скрытый ноутбук (тест-переключатель) |
| `ML_OBJECTS_CACHE` | (нет) | Путь к папке с кэшем RT-DETR от `eval/cache_detections.py` |
| `ML_SAFE_KEY_RULE` | `0` | `1` — включить правило «ключ в замке» (много FP, выключено) |
| `VLM_MODEL` | авто | Переопределить модель VLM (`Qwen/Qwen3-VL-2B-Instruct` или `...-8B-Instruct`) |
| `VLM_DEVICE` | `cuda:0` | Устройство для VLM |
| `VLM_MAX_SIDE` | `448` | Длинная сторона кропа перед подачей в VLM (токены) |

---

## 10. Публичный URL

```bash
cloudflared tunnel --url http://localhost:8000
# Отдать жюри: URL + API_KEY
```

Запускать **один** uvicorn-процесс (без `--workers`, без `--reload`).

---

## 11. Нерешённые вопросы

- X-1, X-2, X-13, X-17, X-44 — тип нарушения не определён
- `workstation_unlocked` — нет прямого нормативного источника
- VLM-тест не завершён — выбор модели не зафиксирован
- Дата дедлайна (12:00) не подтверждена организаторами

---

## 12. Критические ограничения

- **Никаких cloud AI** — OpenAI/Gemini/Claude API = дисквалификация
- **Никаких AGPL** — Ultralytics YOLO запрещён
- **Нет идентификации лиц** — только визуальный/позиционный анализ
- **Нет выдуманных цитат** — весь юртекст из `data/rules.json`; проверить каждую статью на adilet перед сдачей
- **5 минут на видео** — очередь последовательная; 5 видео жюри должны уложиться суммарно
- **После загрузки весов** — сервис работает без интернета
