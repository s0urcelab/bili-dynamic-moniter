import logging
from datetime import datetime, timedelta, timezone

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, get_jwt_identity, set_access_cookies
from werkzeug.exceptions import HTTPException

from bdm import config, db
from bdm.api import admin_system, admin_videos, auth, public
from bdm.api.common import ApiError, JSONProvider, fail
from bdm.logs import setup_logging

logger = logging.getLogger(__name__)


def _setup_jwt(app):
    app.config.update(
        JWT_SECRET_KEY=config.JWT_SECRET_KEY,
        JWT_TOKEN_LOCATION=['cookies'],
        JWT_COOKIE_SECURE=config.JWT_COOKIE_SECURE,
        JWT_COOKIE_SAMESITE='Lax',
        JWT_COOKIE_CSRF_PROTECT=False,
        JWT_SESSION_COOKIE=False,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(weeks=2),
    )
    jwt = JWTManager(app)

    @jwt.unauthorized_loader
    def _missing(reason):
        return fail('未登录', 401)

    @jwt.invalid_token_loader
    def _invalid(reason):
        return fail('登录状态无效，请重新登录', 401)

    @jwt.expired_token_loader
    def _expired(header, payload):
        return fail('登录已过期，请重新登录', 401)

    @app.after_request
    def refresh_expiring_jwt(response):
        try:
            exp = get_jwt()['exp']
            if datetime.timestamp(datetime.now(timezone.utc) + timedelta(days=1)) > exp:
                set_access_cookies(response, create_access_token(identity=get_jwt_identity()))
        except (RuntimeError, KeyError):
            pass
        return response


def _setup_errors(app):
    @app.errorhandler(ApiError)
    def _api_error(err):
        return fail(err.message, err.status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        return fail(err.description or err.name, err.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(err):
        logger.exception('未处理的异常')
        return fail('服务器内部错误', 500)


def create_app():
    config.require('JWT_SECRET_KEY', 'MANAGE_PASSWORD')
    setup_logging()
    db.init()
    db.close()

    app = Flask(__name__, static_folder=None)
    app.json = JSONProvider(app)
    app.teardown_appcontext(lambda exc: db.close())
    _setup_jwt(app)
    _setup_errors(app)

    for bp in (auth.bp, public.bp, admin_videos.bp, admin_system.bp):
        app.register_blueprint(bp)
    return app
