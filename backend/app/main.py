"""FastAPI application entry point."""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from app.config import settings
from app.api import runway, aircraft, track, config, elevation, buildings, helipad


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print(f"[启动] {settings.app_name} v{settings.app_version}")
    print(f"   API 地址: http://{settings.host}:{settings.port}{settings.api_prefix}")
    print(f"   前端页面: http://localhost:{settings.port}")
    print(f"   API 文档: http://localhost:{settings.port}/docs")
    yield
    # Shutdown
    print(f"[关闭] {settings.app_name}")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="飞行营地五边航迹计算与可视化工具后端API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(runway.router, prefix=settings.api_prefix, tags=["跑道参数"])
app.include_router(aircraft.router, prefix=settings.api_prefix, tags=["机型库"])
app.include_router(track.router, prefix=settings.api_prefix, tags=["航迹计算"])
app.include_router(config.router, prefix=settings.api_prefix, tags=["map-config"])
app.include_router(elevation.router, prefix=settings.api_prefix, tags=["elevation"])
app.include_router(buildings.router, prefix=settings.api_prefix, tags=["buildings"])
app.include_router(helipad.router, prefix=settings.api_prefix, tags=["helipad"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# --- Serve frontend static files ---
STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist"
)

if os.path.isdir(STATIC_DIR):
    # Mount static assets (JS, CSS, images, etc.)
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # SPA fallback: serve static files or index.html
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        # Skip API paths (shouldn't reach here, but defensive)
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        # Prevent path traversal
        if ".." in full_path:
            return {"detail": "Not Found"}
        # If a static file exists at this path, serve it directly
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise serve index.html for SPA routing
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"detail": "Frontend not found"}

    # Also serve root path
    @app.get("/")
    async def serve_root():
        index_path = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "docs": "/docs",
        }

    print(f"   静态文件目录: {STATIC_DIR}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
