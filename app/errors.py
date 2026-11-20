from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None):
        self.status, self.code, self.message = status, code, message
        self.headers = headers


def unauthorized():
    return APIError(401, "unauthorized", "Authentication failed.")


def error_response(status: int, code: str, message: str, headers=None):
    response_headers = {"Cache-Control": "no-store", **(headers or {})}
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status, headers=response_headers)
