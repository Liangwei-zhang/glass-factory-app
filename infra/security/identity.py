from __future__ import annotations

CUSTOMER_ROLES = frozenset({"customer", "customer_viewer"})
MANAGER_ROLES = frozenset({"manager", "supervisor"})
ADMIN_ROLES = frozenset({"admin", "super_admin"})

ROLE_SCOPE_DEFAULTS: dict[str, frozenset[str]] = {
    "super_admin": frozenset(
        {
            "orders:read",
            "orders:write",
            "orders:cancel",
            "inventory:read",
            "inventory:write",
            "production:read",
            "production:write",
            "quality:write",
            "logistics:write",
            "finance:read",
            "finance:write",
            "admin:read",
            "admin:write",
            "system:manage",
        }
    ),
    "admin": frozenset(
        {
            "orders:read",
            "orders:write",
            "orders:cancel",
            "inventory:read",
            "inventory:write",
            "production:read",
            "production:write",
            "quality:write",
            "logistics:write",
            "finance:read",
            "finance:write",
            "admin:read",
            "admin:write",
            "system:manage",
        }
    ),
    "manager": frozenset(
        {
            "orders:read",
            "orders:write",
            "orders:cancel",
            "inventory:read",
            "inventory:write",
            "production:read",
            "production:write",
            "quality:write",
            "logistics:write",
            "finance:read",
            "admin:read",
        }
    ),
    "finance": frozenset({"finance:read", "finance:write", "admin:read"}),
    "operator": frozenset(
        {
            "orders:read",
            "orders:write",
            "orders:cancel",
            "inventory:read",
            "production:read",
            "logistics:write",
        }
    ),
    "inspector": frozenset({"orders:read", "production:read", "quality:write"}),
    "customer": frozenset({"orders:read", "orders:write", "finance:read"}),
    "customer_viewer": frozenset({"orders:read", "finance:read"}),
}

ROLE_IMPLICATIONS: dict[str, frozenset[str]] = {
    "super_admin": frozenset(
        {
            "super_admin",
            "admin",
            "manager",
            "finance",
            "operator",
            "inspector",
        }
    ),
    "admin": frozenset({"admin", "manager", "finance", "operator", "inspector"}),
    "manager": frozenset({"manager", "operator", "inspector"}),
    "finance": frozenset({"finance"}),
    "operator": frozenset({"operator"}),
    "inspector": frozenset({"inspector"}),
    "customer": frozenset({"customer", "customer_viewer"}),
    "customer_viewer": frozenset({"customer_viewer"}),
}

STAGE_LABELS: dict[str, str] = {
    "cutting": "切玻璃工人",
    "edging": "开切口工人",
    "tempering": "钢化工人",
    "finishing": "完成钢化处工人",
}


def normalize_role(role: str | None) -> str:
    return str(role or "").strip().lower()


def resolve_home_path(role: str | None) -> str:
    canonical_role = resolve_canonical_role(role)
    if canonical_role in CUSTOMER_ROLES:
        return "/app"
    if canonical_role in {"admin", "super_admin", "manager", "finance"}:
        return "/admin"
    return "/platform"


def resolve_shell_name(role: str | None) -> str:
    home_path = resolve_home_path(role)
    if home_path == "/app":
        return "app"
    if home_path == "/admin":
        return "admin"
    return "platform"


def resolve_stage_label(stage: str | None) -> str | None:
    normalized = str(stage or "").strip().lower()
    if not normalized:
        return None
    return STAGE_LABELS.get(normalized, normalized)


def resolve_canonical_role(role: str | None) -> str:
    normalized = normalize_role(role)
    if normalized == "supervisor":
        return "manager"
    if normalized in {"office", "worker"}:
        return "operator"
    return normalized or "operator"


def resolve_user_scopes(
    role: str | None,
    scopes: list[str] | None = None,
    stage: str | None = None,
) -> list[str]:
    normalized_stage = str(stage or "").strip().lower()
    canonical_role = resolve_canonical_role(role)
    resolved_scopes = set(ROLE_SCOPE_DEFAULTS.get(canonical_role, frozenset()))
    resolved_scopes.update(str(scope).strip() for scope in (scopes or []) if str(scope).strip())

    # Compatibility bridge while the workspace still carries pre-sj roles.
    legacy_role = normalize_role(role)
    is_stage_operator = canonical_role == "operator" and bool(normalized_stage)
    if legacy_role == "worker" or is_stage_operator:
        resolved_scopes.update({"production:read", "production:write", "orders:read"})
        resolved_scopes.difference_update({"orders:write", "orders:cancel", "logistics:write"})
    if legacy_role == "office":
        resolved_scopes.update({"orders:read", "orders:write", "orders:cancel", "logistics:write"})

    return sorted(resolved_scopes)


def role_satisfies(user_role: str | None, required_role: str | None) -> bool:
    required = resolve_canonical_role(required_role)
    user_canonical_role = resolve_canonical_role(user_role)
    implied_roles = ROLE_IMPLICATIONS.get(user_canonical_role, frozenset({user_canonical_role}))
    return required in implied_roles


def can_create_orders(role: str | None) -> bool:
    return normalize_role(role) == "customer"
