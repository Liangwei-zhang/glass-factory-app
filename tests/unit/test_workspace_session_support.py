from __future__ import annotations

from domains.workspace import session_support
from infra.db.models.users import UserModel


def test_serialize_workspace_user_emits_canonical_role_fields() -> None:
    user = UserModel(
        id="user-1",
        display_name="Operations Desk",
        email="office@glass.local",
        role="office",
        stage=None,
        customer_id=None,
        scopes=["orders:write"],
    )

    payload = session_support.serialize_workspace_user(user)

    assert payload["role"] == "operator"
    assert payload["canonicalRole"] == "operator"
    assert payload["homePath"] == "/platform"
    assert payload["shell"] == "platform"
    assert payload["canCreateOrders"] is False


def test_build_workspace_summary_includes_worker_queue_metrics() -> None:
    orders = [
        {
            "status": "in_production",
            "isStale": False,
            "priority": "rush",
            "reworkOpen": True,
            "isModified": False,
            "steps": [
                {"key": "cutting", "status": "pending", "isAvailable": True},
            ],
        },
        {
            "status": "ready_for_pickup",
            "isStale": True,
            "priority": "normal",
            "reworkOpen": False,
            "isModified": True,
            "steps": [
                {"key": "cutting", "status": "completed", "isAvailable": False},
            ],
        },
    ]
    customers = [
        {"hasActiveOrders": True},
        {"hasActiveOrders": False},
    ]

    summary = session_support.build_workspace_summary(
        orders,
        customers,
        role="operator",
        stage="cutting",
    )

    assert summary["totalOrders"] == 2
    assert summary["activeOrders"] == 2
    assert summary["rushOrders"] == 1
    assert summary["reworkOrders"] == 1
    assert summary["modifiedOrders"] == 1
    assert summary["activeCustomers"] == 1
    assert summary["workerQueue"] == 1
    assert summary["workerReady"] == 1