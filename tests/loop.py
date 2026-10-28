"""One event loop for the tests' own database calls (the app runs in the TestClient's)."""
import asyncio

_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)
