"""FastAPI middleware for logging requests with bodies to JSON file."""

import json
import time
from pathlib import Path
from typing import Callable, Awaitable, TextIO

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.settings import settings


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Logs incoming requests with their bodies to a JSON file."""

    def __init__(self, app):
        super().__init__(app)
        self._log_file: TextIO | None = None
        self._current_log_path: str | None = None

    def __del__(self):
        """Close log file when middleware is destroyed."""
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Check if logging path has changed
        current_path = settings.request_log_path
        
        # If path changed or we don't have a file open, reconfigure
        if current_path != self._current_log_path:
            # Close old file if open
            if self._log_file:
                self._log_file.close()
            
            # Open new file if path is set
            if current_path:
                log_path = Path(current_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self._log_file = log_path.open("a", encoding="utf-8")
                except IOError as e:
                    import sys
                    print(f"WARNING: Failed to open request log file {log_path}: {e}", file=sys.stderr)
                    self._log_file = None
            else:
                self._log_file = None
            
            self._current_log_path = current_path
        
        # Early exit if no log file
        if self._log_file is None:
            return await call_next(request)

        # Only log POST/PUT/PATCH requests (likely to have bodies)
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        # Read request body
        body_bytes = await request.body()
        try:
            body_text = body_bytes.decode("utf-8")
            body_json = json.loads(body_text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            body_json = {"_raw": body_bytes.hex()}  # Fallback for binary/non-JSON

        # Capture request info
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime())

        log_entry = {
            "timestamp": timestamp,
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
            "body": body_json,
        }

        # Write to pre-opened file
        try:
            json.dump(log_entry, self._log_file)
            self._log_file.write("\n")
            self._log_file.flush()  # Ensure immediate write
        except IOError as e:
            import sys
            print(f"ERROR: Failed to write request log: {e}", file=sys.stderr)

        # Reconstruct request with body for downstream handlers
        request.state._body = body_bytes
        request._body = body_bytes

        # Call the next handler and capture any exceptions
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            # Log the error with the request
            error_log = {
                "timestamp": timestamp,
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "query_params": dict(request.query_params),
                "body": body_json,
                "error": str(e),
                "error_type": type(e).__name__,
            }
            try:
                json.dump(error_log, self._log_file)
                self._log_file.write("\n")
                self._log_file.flush()
            except IOError:
                pass  # Don't let logging failures mask the original error
            raise
