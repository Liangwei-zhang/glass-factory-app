from __future__ import annotations

from infra.security.identity import (
    can_create_orders,
    resolve_canonical_role,
    resolve_home_path,
    resolve_shell_name,
    resolve_stage_label,
    resolve_user_scopes,
    role_satisfies,
)


def test_identity_helpers_cover_customer_viewer_and_stage_labels() -> None:
    assert resolve_home_path("customer_viewer") == "/app"
    assert resolve_shell_name("manager") == "admin"
    assert resolve_stage_label("cutting") == "切玻璃工人"
    assert can_create_orders("customer") is True
    assert can_create_orders("customer_viewer") is False


def test_canonical_role_mapping_preserves_customer_roles_and_collapses_legacy_workspace_roles() -> (
    None
):
    assert resolve_canonical_role("customer") == "customer"
    assert resolve_canonical_role("customer_viewer") == "customer_viewer"
    assert resolve_canonical_role("admin") == "admin"
    assert resolve_canonical_role("manager") == "manager"
    assert resolve_canonical_role("supervisor") == "manager"
    assert resolve_canonical_role("worker") == "operator"
    assert resolve_canonical_role("office") == "operator"


def test_canonical_role_and_scope_resolution_bridge_legacy_roles() -> None:
    assert resolve_canonical_role("office") == "operator"
    assert resolve_canonical_role("worker") == "operator"
    assert resolve_canonical_role("supervisor") == "manager"

    office_scopes = resolve_user_scopes("office")
    worker_scopes = resolve_user_scopes("worker", stage="cutting")
    operator_scopes = resolve_user_scopes("operator", stage="cutting")
    viewer_scopes = resolve_user_scopes("customer_viewer")

    assert "orders:write" in office_scopes
    assert "logistics:write" in office_scopes
    assert "production:write" in worker_scopes
    assert "production:write" in operator_scopes
    assert "orders:write" not in worker_scopes
    assert "orders:cancel" not in worker_scopes
    assert "orders:write" not in operator_scopes
    assert "orders:read" in viewer_scopes
    assert "orders:write" not in viewer_scopes


def test_role_satisfies_hierarchy_supports_canonical_and_customer_roles() -> None:
    assert role_satisfies("supervisor", "manager") is True
    assert role_satisfies("admin", "operator") is True
    assert role_satisfies("customer", "customer_viewer") is True
    assert role_satisfies("customer_viewer", "customer") is False
