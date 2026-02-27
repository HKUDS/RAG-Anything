import asyncio
import logging

# Global event to signal shutdown
shutdown_event = asyncio.Event()

# Store background tasks for cancellation
background_tasks = set()

logger = logging.getLogger(__name__)


def add_background_task(task: asyncio.Task):
    """Add a task to the background tasks set for cancellation tracking"""
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def check_shutdown():
    """Check if shutdown has been requested and raise if so"""
    if shutdown_event.is_set():
        raise asyncio.CancelledError("Server is shutting down")


async def run_with_cancellation(coro, description: str = "Operation"):
    """
    Run a coroutine with cancellation support for graceful shutdown
    """
    try:
        # Check if shutdown has been requested before starting
        await check_shutdown()

        # Create a task that can be cancelled
        task = asyncio.create_task(coro)
        add_background_task(task)

        try:
            # Periodically check for shutdown while running
            while not task.done():
                await check_shutdown()
                await asyncio.sleep(0.5)  # Check every 500ms

            return await task

        except asyncio.CancelledError:
            logger.info(f"{description} cancelled due to server shutdown")
            # Attempt to cancel the underlying task
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            raise

    except asyncio.CancelledError:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail=f"{description} was cancelled due to server shutdown",
        )


def trigger_shutdown():
    """Trigger shutdown event"""
    shutdown_event.set()


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested"""
    return shutdown_event.is_set()


async def cancel_all_background_tasks():
    """Cancel all background tasks"""
    tasks_to_cancel = [task for task in background_tasks if not task.done()]
    if tasks_to_cancel:
        logger.info(f"Cancelling {len(tasks_to_cancel)} running tasks...")
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
