"""HIS 服務化 Flask API（app factory＋blueprints）。

用法：
    from elc_audit_engine.api import create_app
    app = create_app()
"""

from .app import create_app

__all__ = ["create_app"]
