import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.v1.endpoints import crawler, search, agent
from app.core.config import settings

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.path.exists(settings.DATA_DIR):
        os.makedirs(settings.DATA_DIR)
    yield

app = FastAPI(title="TruyenFull Crawler", lifespan=lifespan)

app.include_router(crawler.router, prefix="/api/v1", tags=["crawler"])
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["agent"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("app/static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
