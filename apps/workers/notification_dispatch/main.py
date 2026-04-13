from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from infra.db.models.events import EventOutboxModel
from infra.db.models.notifications import NotificationModel
from infra.db.models.users import UserModel
from infra.db.session import build_session_factory
from infra.events.topics import Topics
from infra.security.identity import resolve_canonical_role

HANDLED_TOPICS = {
    Topics.ORDER_CREATED,
    Topics.ORDER_CONFIRMED,
    Topics.ORDER_ENTERED,
    Topics.ORDER_PRODUCING,
    Topics.ORDER_COMPLETED,
    Topics.ORDER_READY_FOR_PICKUP,
    Topics.ORDER_PICKED_UP,
    Topics.ORDER_CANCELLED,
    Topics.PRODUCTION_SCHEDULED,
    Topics.PRODUCTION_STARTED,
    Topics.PRODUCTION_COMPLETED,
    Topics.PRODUCTION_REWORK_REQUESTED,
    Topics.PRODUCTION_REWORK_ACKNOWLEDGED,
    Topics.LOGISTICS_SHIPPED,
    Topics.LOGISTICS_DELIVERED,
    Topics.INVENTORY_LOW_STOCK,
}


def _build_notification(event: EventOutboxModel) -> tuple[str, str, str]:
    payload = event.payload or {}
    order_no = str(payload.get("order_no") or payload.get("order_id") or "unknown-order")

    if event.topic == Topics.ORDER_CREATED:
        return "Order created", f"Order {order_no} has been created.", "info"
    if event.topic == Topics.ORDER_CONFIRMED:
        return "Order confirmed", f"Order {order_no} has been confirmed.", "info"
    if event.topic == Topics.ORDER_ENTERED:
        return "Order entered", f"Order {order_no} has entered production queue.", "info"
    if event.topic == Topics.ORDER_PRODUCING:
        return "Order in production", f"Order {order_no} is now in production.", "info"
    if event.topic == Topics.ORDER_COMPLETED:
        return "Order completed", f"Order {order_no} has been completed.", "success"
    if event.topic == Topics.ORDER_READY_FOR_PICKUP:
        return "Ready for pickup", f"Order {order_no} is ready for pickup.", "success"
    if event.topic == Topics.ORDER_PICKED_UP:
        return "Order picked up", f"Order {order_no} has been picked up.", "info"
    if event.topic == Topics.ORDER_CANCELLED:
        reason = str(payload.get("reason") or "")
        suffix = f" Reason: {reason}." if reason else ""
        return "Order cancelled", f"Order {order_no} has been cancelled.{suffix}", "warning"
    if event.topic == Topics.PRODUCTION_SCHEDULED:
        line_id = str(payload.get("line_id") or "")
        line_suffix = f" on line {line_id}" if line_id else ""
        return "Production scheduled", f"Work order {order_no} is scheduled{line_suffix}.", "info"
    if event.topic == Topics.PRODUCTION_STARTED:
        return "Production started", f"Work order {order_no} has started.", "info"
    if event.topic == Topics.PRODUCTION_COMPLETED:
        return "Production completed", f"Work order {order_no} is completed.", "success"
    if event.topic == Topics.PRODUCTION_REWORK_REQUESTED:
        return "Rework requested", f"Work order {order_no} requested rework.", "warning"
    if event.topic == Topics.PRODUCTION_REWORK_ACKNOWLEDGED:
        return "Rework acknowledged", f"Work order {order_no} rework was acknowledged.", "info"
    if event.topic == Topics.LOGISTICS_SHIPPED:
        return "Shipment dispatched", f"Order {order_no} is in transit.", "info"
    if event.topic == Topics.LOGISTICS_DELIVERED:
        return "Shipment delivered", f"Order {order_no} has been delivered.", "success"
    if event.topic == Topics.INVENTORY_LOW_STOCK:
        product_id = str(payload.get("product_id") or "unknown-product")
        available_qty = payload.get("available_qty")
        return (
            "Low stock alert",
            f"Product {product_id} is below safety stock. Available: {available_qty}.",
            "warning",
        )
    return "System event", f"Event {event.topic} received.", "info"


def _resolve_target_user_ids(event: EventOutboxModel, active_users: list[UserModel]) -> list[str]:
    payload = event.payload or {}
    active_user_ids = {str(user.id) for user in active_users}
    requested_ids = payload.get("notify_user_ids")
    if isinstance(requested_ids, list):
        return [str(user_id) for user_id in requested_ids if str(user_id) in active_user_ids]

    manager_like_ids = {
        str(user.id)
        for user in active_users
        if resolve_canonical_role(user.role) in {"manager", "admin", "super_admin"}
    }
    office_ids = {
        str(user.id)
        for user in active_users
        if resolve_canonical_role(user.role) == "operator" and not user.stage
    }

    internal_ops_topics = {
        Topics.ORDER_CREATED,
        Topics.ORDER_CONFIRMED,
        Topics.ORDER_ENTERED,
        Topics.ORDER_PRODUCING,
        Topics.ORDER_COMPLETED,
        Topics.ORDER_READY_FOR_PICKUP,
        Topics.ORDER_PICKED_UP,
        Topics.ORDER_CANCELLED,
        Topics.LOGISTICS_SHIPPED,
        Topics.LOGISTICS_DELIVERED,
        Topics.INVENTORY_LOW_STOCK,
    }

    if event.topic in internal_ops_topics:
        return sorted(manager_like_ids | office_ids)

    if event.topic in {
        Topics.PRODUCTION_SCHEDULED,
        Topics.PRODUCTION_STARTED,
        Topics.PRODUCTION_COMPLETED,
        Topics.PRODUCTION_REWORK_REQUESTED,
        Topics.PRODUCTION_REWORK_ACKNOWLEDGED,
    }:
        target_stage = str(payload.get("step_key") or payload.get("process_step_key") or "").strip()
        if event.topic == Topics.PRODUCTION_REWORK_REQUESTED:
            target_stage = "cutting"
        stage_operator_ids = {
            str(user.id)
            for user in active_users
            if resolve_canonical_role(user.role) == "operator"
            and (user.stage or "").strip().lower() == target_stage.lower()
        }
        return sorted((manager_like_ids | stage_operator_ids) or manager_like_ids)

    return sorted(manager_like_ids or active_user_ids)


async def run_once(batch_size: int = 200) -> int:
    session_factory = build_session_factory()
    async with session_factory() as session:
        event_result = await session.execute(
            select(EventOutboxModel)
            .where(
                EventOutboxModel.status == "published",
                EventOutboxModel.topic.in_(HANDLED_TOPICS),
            )
            .order_by(EventOutboxModel.published_at.asc(), EventOutboxModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(event_result.scalars().all())
        pending_rows = [
            row for row in rows if not bool((row.headers or {}).get("notification_dispatched"))
        ]
        if not pending_rows:
            return 0

        user_result = await session.execute(
            select(UserModel).where(UserModel.is_active.is_(True))
        )
        active_users = list(user_result.scalars().all())

        sent_count = 0
        dispatch_time = datetime.now(timezone.utc).isoformat()
        for event in pending_rows:
            title, message, severity = _build_notification(event)
            order_id = event.payload.get("order_id") if isinstance(event.payload, dict) else None
            target_user_ids = _resolve_target_user_ids(event, active_users)

            for user_id in target_user_ids:
                session.add(
                    NotificationModel(
                        user_id=user_id,
                        order_id=str(order_id) if order_id else None,
                        title=title,
                        message=message,
                        severity=severity,
                        is_read=False,
                    )
                )
                sent_count += 1

            headers = dict(event.headers or {})
            headers["notification_dispatched"] = True
            headers["notification_dispatched_at"] = dispatch_time
            headers["notification_dispatch_count"] = len(target_user_ids)
            event.headers = headers

        await session.commit()

    logger.info(
        "notification-dispatch worker created notifications count={} events={}",
        sent_count,
        len(pending_rows),
    )
    return sent_count
