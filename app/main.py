from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .api import routes
import os, logging
from logging.handlers import RotatingFileHandler

app = FastAPI(title="Chatbot Hybrid API")

# Mount static files (CSS, JS, Images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include API routes
app.include_router(routes.router)

@app.get("/")
def read_root():
    return {"message": "Selamat datang di API Chatbot Hybrid"}


def setup_logging():
    os.makedirs("logs", exist_ok=True)
    handler = RotatingFileHandler("logs/chat.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

setup_logging()