"""Convenience entry point for a local FastAPI server."""
import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
