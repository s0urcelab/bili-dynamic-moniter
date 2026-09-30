import hmac

from flask import Blueprint
from flask_jwt_extended import (create_access_token, get_jwt_identity, set_access_cookies,
                                unset_jwt_cookies, verify_jwt_in_request)

from bdm import config
from bdm.api.common import ApiError, body, ok

bp = Blueprint('auth', __name__, url_prefix='/api/auth')

ADMIN = 'admin'


def is_admin():
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return False
    return get_jwt_identity() == ADMIN


@bp.post('/login')
def login():
    password = str(body().get('password') or '')
    if not hmac.compare_digest(password.encode(), config.MANAGE_PASSWORD.encode()):
        raise ApiError('密码错误', 401)
    resp = ok({'logged_in': True}, '登录成功')
    set_access_cookies(resp, create_access_token(identity=ADMIN))
    return resp


@bp.post('/logout')
def logout():
    resp = ok({'logged_in': False}, '已退出登录')
    unset_jwt_cookies(resp)
    return resp


@bp.get('/me')
def me():
    return ok({'logged_in': is_admin()})
