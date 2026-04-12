from __future__ import annotations

from infra.security.auth import create_access_token, decode_access_token


def test_access_token_round_trip_preserves_customer_id_claim() -> None:
    token = create_access_token(
        subject="user-123",
        role="customer",
        scopes=["orders:read"],
        customer_id="cust-123",
        session_id="session-123",
    )

    user = decode_access_token(token)

    assert user.user_id == "user-123"
    assert user.role == "customer"
    assert user.customer_id == "cust-123"
    assert user.session_id == "session-123"