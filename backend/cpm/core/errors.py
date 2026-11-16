import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg

log = logging.getLogger("cpm.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details


def NotFound(what: str = "resource") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def body(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, **({"details": details} if details else {})}
    }


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(body(e.code, e.message, e.details), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        errs = [
            {"field": ".".join(str(p) for p in x["loc"][1:]), "message": x["msg"]}
            for x in e.errors()
        ]
        return JSONResponse(
            body("validation_error", "Invalid request", {"errors": errs}), status_code=422
        )

    @app.exception_handler(pg.InsufficientPrivilege)
    async def _priv(_: Request, e: Exception):
        return JSONResponse(body("forbidden", "Not allowed"), status_code=403)

    @app.exception_handler(pg.IntegrityError)
    async def _integrity(_: Request, e: Exception):
        log.warning("integrity error: %s", e)
        return JSONResponse(body("conflict", "The change violates a data rule"), status_code=409)

    @app.exception_handler(Exception)
    async def _any(_: Request, e: Exception):
        log.exception("unhandled error")  # no tokens/credentials are ever logged
        return JSONResponse(body("internal_error", "Something went wrong"), status_code=500)
