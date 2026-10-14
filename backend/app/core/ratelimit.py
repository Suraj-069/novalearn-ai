"""Tiny in-memory sliding-window rate limiter for auth endpoints.

Limitation: per-process memory only. Use a shared store (e.g. Redis) behind
multiple workers. Good enough for a single-process prototype.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self.hits.clear()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
        q.append(now)


auth_limiter = RateLimiter(max_calls=20, window_seconds=60)
