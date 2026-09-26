"""API 錯誤型別與統一錯誤處理（P0-1 脫敏、P0-2 故障與業務結論可區分）。"""

from __future__ import annotations

from flask import Flask, current_app, jsonify
from werkzeug.exceptions import HTTPException

from elc_audit_engine.auth import AuthenticationError
from elc_audit_engine.safe_paths import UnsafeIdentifierError


class ApiError(Exception):
    """可安全回傳給前端的錯誤（訊息不含內部細節）。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class UploadFileError(Exception):
    """上傳檔案不合法（副檔名／大小）。"""


def _error(message: str, status: int):
    return jsonify({"status": "error", "message": message}), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AuthenticationError)
    def _handle_authentication_error(exc: AuthenticationError):
        """認證失敗一律回 401，且必須與「查無資料」可區分（P0-2／P1-1 同源原則）。"""
        return _error(exc.message, 401)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return _error(exc.message, exc.status)

    @app.errorhandler(UnsafeIdentifierError)
    def _handle_unsafe_identifier(exc: UnsafeIdentifierError):
        """不合法的識別碼（含路徑成分等）是呼叫方錯誤，回 400 而非 500。"""
        return _error(str(exc), 400)

    @app.errorhandler(UploadFileError)
    def _handle_upload_error(exc: UploadFileError):
        return _error(str(exc), 400)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        """保留 Flask/werkzeug 的 4xx/405 語意（404 探測、415 Content-Type、400 JSON 語法）。

        Flask 依例外 MRO 選最具體的 handler，故此 handler 優先於下方
        Exception 兜底；否則呼叫方送錯的請求會被誤報成 500（P0-2）。
        """
        return _error(exc.description, exc.code)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        """統一脫敏：不把 traceback／內部路徑回給前端（P0-1 debug 回顯）。"""
        current_app.logger.exception("unhandled error: %s", exc)
        return _error("伺服器內部錯誤，請聯繫系統管理員", 500)
