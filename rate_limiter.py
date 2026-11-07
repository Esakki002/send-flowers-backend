import time
import asyncio
import logging
from typing import Dict, List, Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

logger = logging.getLogger("sendflowers.security")

class SlidingWindowRateLimiter:
    """
    In-memory thread-safe sliding window rate limiter per client IP and endpoint group.
    """
    def __init__(self):
        # Key: (ip, bucket) -> list of timestamp floats
        self._history: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        """Resolve client IP from reverse proxy headers or direct connection."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            logger.debug("Resolved client IP from x-forwarded-for: %s", ip)
            return ip
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            ip = real_ip.strip()
            logger.debug("Resolved client IP from x-real-ip: %s", ip)
            return ip
        ip = request.client.host if request.client else "127.0.0.1"
        logger.debug("Resolved client IP from client host: %s", ip)
        return ip

    def _get_route_bucket(self, path: str) -> tuple[str, int, int]:
        """
        Returns (bucket_name, max_requests, window_seconds)
        """
        if path.startswith("/api/payment/create-order"):
            return ("create_order", 15, 60)
        elif path.startswith("/api/payment/verify-payment"):
            return ("verify_payment", 20, 60)
        elif path.startswith("/api/card"):
            return ("get_card", 80, 60)
        elif path.startswith("/api/orders"):
            return ("get_orders", 40, 60)
        elif path.startswith("/api/"):
            return ("api_general", 120, 60)
        return ("default", 200, 60)

    async def check_rate_limit(self, request: Request):
        path = request.url.path
        # Skip health check from strict rate limits
        if path == "/api/health":
            logger.debug("Bypassing rate limit check for health endpoint: %s", path)
            return

        bucket, max_requests, window = self._get_route_bucket(path)
        client_ip = self._get_client_ip(request)
        key = f"{client_ip}:{bucket}"
        now = time.time()

        async with self._lock:
            # Periodic cleanup of old entries every 5 minutes
            if now - self._last_cleanup > 300:
                self._cleanup(now)
                self._last_cleanup = now

            timestamps = self._history.get(key, [])
            # Filter out timestamps outside window
            cutoff = now - window
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) >= max_requests:
                earliest = valid_timestamps[0]
                retry_after = max(1, int(cutoff - earliest + window))
                logger.warning(
                    "Rate limit EXCEEDED for IP='%s' on bucket='%s' (path='%s'). Count=%d/%d in %ds window. Retry-After=%ds",
                    client_ip,
                    bucket,
                    path,
                    len(valid_timestamps),
                    max_requests,
                    window,
                    retry_after,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Please wait {retry_after} seconds before retrying.",
                    headers={"Retry-After": str(retry_after)},
                )

            valid_timestamps.append(now)
            self._history[key] = valid_timestamps
            logger.debug(
                "Rate limit check passed: IP='%s' bucket='%s' (%d/%d used)",
                client_ip,
                bucket,
                len(valid_timestamps),
                max_requests,
            )

    def _cleanup(self, now: float):
        cutoff = now - 3600  # Remove keys inactive for over an hour
        keys_to_delete = []
        for k, timestamps in self._history.items():
            valid = [t for t in timestamps if t > cutoff]
            if not valid:
                keys_to_delete.append(k)
            else:
                self._history[k] = valid
        for k in keys_to_delete:
            del self._history[k]
        if keys_to_delete:
            logger.info("Evicted %d stale IP buckets from rate limiter memory cache.", len(keys_to_delete))

limiter = SlidingWindowRateLimiter()

class RateLimitAndSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Enforce rate limiting on API paths (skip OPTIONS preflight and health check)
        if request.method != "OPTIONS" and request.url.path.startswith("/api"):
            try:
                await limiter.check_rate_limit(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers or {},
                )

        # 2. Process request
        response: Response = await call_next(request)

        # 3. Add protective security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "microphone=(self), camera=()"

        return response
