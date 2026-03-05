import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .routes import router
from .core import initialize_rag, cleanup_rag
from .utils import cancel_all_background_tasks

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan with proper cleanup"""
    logger.info("RAG-Anything Service starting up...")

    # Initialize RAG instance in app state
    try:
        app.state.rag_instance = await initialize_rag()
        logger.info("RAG instance initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize RAG instance: {e}")
        raise

    yield

    # Shutdown cleanup
    logger.info("RAG-Anything Service shutting down...")
    try:
        # Cancel all background tasks
        await cancel_all_background_tasks()

        # Cleanup RAG instance
        await cleanup_rag(app.state.rag_instance)

        logger.info("RAG-Anything Service shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


app = FastAPI(title="RAG-Anything Service", version="0.1.0", lifespan=lifespan)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS for local UI dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root path to API documentation"""
    return RedirectResponse(url="/docs")
