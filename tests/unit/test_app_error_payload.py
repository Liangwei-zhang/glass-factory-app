from infra.core.errors import AppError


def test_app_error_payload_shape() -> None:
    err = AppError(code="E_TEST", message="test", status_code=400, details={"k": "v"})
    payload = err.to_payload()

    assert payload["error"] == {
        "code": "E_TEST",
        "message": "test",
        "details": {"k": "v"},
    }
    assert "timestamp" in payload
