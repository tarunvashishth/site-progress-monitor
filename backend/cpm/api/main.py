from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cpm.api.routers import projects, reports, videos
from cpm.core import errors
from cpm.core.config import get_settings

app = FastAPI(title="Construction Progress Monitor API", version="0.1.0")
errors.install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],  # restricted: never "*"
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(projects.router)
app.include_router(videos.router)
app.include_router(reports.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
