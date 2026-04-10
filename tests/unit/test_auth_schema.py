from __future__ import annotations

from domains.auth.schema import LoginRequest


def test_login_request_principal_prefers_username() -> None:
    payload = LoginRequest(username="alice", email="alice@example.com", password="secret")

    assert payload.principal == "alice"


def test_login_request_principal_falls_back_to_email() -> None:
    payload = LoginRequest(username=None, email=" user@example.com ", password="secret")

    assert payload.principal == "user@example.com"


def test_login_request_principal_falls_back_to_phone() -> None:
    payload = LoginRequest(username=None, email=None, phone=" 13800138000 ", password="secret")

    assert payload.principal == "13800138000"


def test_login_request_principal_supports_social_alias_fields() -> None:
    payload = LoginRequest(
        username=None,
        email=None,
        phone=None,
        whatsappId=" wa_user_1 ",
        wechatId="wx_user_1",
        password="secret",
    )

    assert payload.principal == "wa_user_1"
