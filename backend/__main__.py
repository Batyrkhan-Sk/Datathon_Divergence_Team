"""python -m backend  ->  uvicorn on $HOST:$PORT (default 0.0.0.0:8000). Run from the repo root."""
import os

import uvicorn

from .app.config import ROOT

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    uvicorn.run("backend.app.main:app", host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")), workers=1)
