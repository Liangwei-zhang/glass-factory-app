from __future__ import annotations

import base64
import binascii
import smtplib
from datetime import datetime, timezone
from decimal import Decimal
from email.message import EmailMessage
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.service import CustomersService
from domains.inventory.schema import InventoryReservationItem, InventoryReservationRequest
from domains.inventory.service import InventoryService
from domains.orders.errors import order_not_found
from domains.orders.repository import OrdersRepository
from domains.orders.schema import (
    CreateOrderRequest,
    OrderStatus,
    OrderTimelineEvent,
    OrderView,
    UpdateOrderRequest,
    can_transition_order_status,
)
from infra.core.errors import AppError, ErrorCode
from infra.core.id_generator import OrderIdGenerator
from infra.db.models.events import EventOutboxModel
from infra.db.models.logistics import ShipmentModel
from infra.db.models.customers import CustomerModel
from infra.db.models.orders import OrderModel
from infra.db.models.production import QualityCheckModel, WorkOrderModel
from infra.db.models.settings import EmailLogModel, NotificationTemplateModel
from infra.events.outbox import OutboxPublisher
from infra.events.topics import Topics
from infra.core.config import get_settings
from infra.security.identity import resolve_canonical_role
from infra.storage.object_storage import ObjectStorage


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    raw = data_url.strip()
    if not raw.startswith("data:") or "," not in raw:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid signature payload.",
            status_code=400,
        )

    header, encoded = raw.split(",", maxsplit=1)
    extension = "png"
    if "image/jpeg" in header or "image/jpg" in header:
        extension = "jpg"

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid signature payload.",
            status_code=400,
        ) from exc

    return decoded, extension


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_minimal_pdf(lines: list[str]) -> bytes:
    content_parts = ["BT", "/F1 12 Tf", "48 790 Td"]
    for index, line in enumerate(lines):
        escaped = _escape_pdf_text(line)
        if index == 0:
            content_parts.append(f"({escaped}) Tj")
        else:
            content_parts.append(f"0 -18 Td ({escaped}) Tj")
    content_parts.append("ET")
    stream = "\n".join(content_parts).encode("utf-8")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n",
    ]

    header = b"%PDF-1.4\n"
    body = bytearray(header)
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)

    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    body.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return bytes(body)


PROCESS_STEP_SEQUENCE = ("cutting", "edging", "tempering", "finishing")
PROCESS_STEP_INDEX = {step: index for index, step in enumerate(PROCESS_STEP_SEQUENCE)}
STEP_LABELS = {
    "cutting": "切玻璃",
    "edging": "开切口",
    "tempering": "钢化",
    "finishing": "完成钢化",
}
PRIORITY_VALUES = {"normal", "rush", "rework", "hold"}
PICKUP_TEMPLATE_KEY = "ready_for_pickup"
DEFAULT_PICKUP_TEMPLATE_NAME = "Ready for Pickup 邮件"
DEFAULT_PICKUP_TEMPLATE_SUBJECT = "订单 {{orderNo}} 已可取货"
DEFAULT_PICKUP_TEMPLATE_BODY = (
    "您好 {{customerName}}，\n\n"
    "订单 {{orderNo}} 已可取货。\n"
    "玻璃类型：{{glassType}}\n"
    "规格：{{specification}}\n"
    "数量：{{quantity}}\n\n"
    "请安排到厂取货。\n"
)


def _normalize_priority(priority: str | None) -> str:
    candidate = (priority or "normal").strip().lower()
    if candidate not in PRIORITY_VALUES:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported priority.",
            status_code=400,
            details={"priority": priority},
        )
    return candidate


def _render_template(raw: str, variables: dict[str, str]) -> str:
    rendered = raw
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _serialize_email_log(log: EmailLogModel, order_no: str | None) -> dict:
    return {
        "id": log.id,
        "templateKey": log.template_key,
        "orderId": log.order_id,
        "orderNo": order_no,
        "customerEmail": log.customer_email,
        "subject": log.subject,
        "body": log.body,
        "status": log.status,
        "transport": log.transport,
        "errorMessage": log.error_message,
        "providerMessageId": log.provider_message_id,
        "createdAt": log.created_at,
        "sentAt": log.sent_at,
    }


def _normalize_step_key(step_key: str) -> str:
    normalized = step_key.strip().lower()
    if normalized not in PROCESS_STEP_INDEX:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported process step.",
            status_code=400,
            details={"step_key": step_key},
        )
    return normalized


def _next_process_step(step_key: str) -> str | None:
    index = PROCESS_STEP_INDEX[step_key]
    if index + 1 >= len(PROCESS_STEP_SEQUENCE):
        return None
    return PROCESS_STEP_SEQUENCE[index + 1]


EDITABLE_QUANTITY_ORDER_STATUSES = frozenset({"pending", "confirmed", "entered"})
CONFIRMED_INVENTORY_ORDER_STATUSES = frozenset(
    {"confirmed", "entered", "in_production", "completed", "ready_for_pickup", "picked_up"}
)
PRODUCTION_ACTION_ORDER_STATUSES = frozenset({"entered", "in_production"})


def _order_requires_confirmed_inventory(status: str) -> bool:
    return status in CONFIRMED_INVENTORY_ORDER_STATUSES


def _raise_invalid_order_transition(
    *,
    order_id: str,
    current_status: str,
    target_status: str,
    message: str,
) -> None:
    raise AppError(
        code=ErrorCode.ORDER_INVALID_TRANSITION,
        message=message,
        status_code=409,
        details={
            "order_id": order_id,
            "status": current_status,
            "current_status": current_status,
            "target_status": target_status,
        },
    )


def _ensure_order_transition(
    *,
    order_id: str,
    current_status: str,
    target_status: str,
    message: str,
) -> None:
    if can_transition_order_status(current_status, target_status):
        return
    _raise_invalid_order_transition(
        order_id=order_id,
        current_status=current_status,
        target_status=target_status,
        message=message,
    )


class OrdersService:
    def __init__(
        self,
        repository: OrdersRepository | None = None,
        inventory_service: InventoryService | None = None,
        id_generator: OrderIdGenerator | None = None,
        customers_service: CustomersService | None = None,
    ) -> None:
        self.repository = repository or OrdersRepository()
        self.inventory_service = inventory_service or InventoryService()
        self.id_generator = id_generator or OrderIdGenerator()
        self.customers_service = customers_service or CustomersService()

    async def create_order(self, session: AsyncSession, payload: CreateOrderRequest) -> OrderView:
        normalized_priority = _normalize_priority(payload.priority)
        payload = payload.model_copy(update={"priority": normalized_priority})

        if payload.idempotency_key:
            existing = await self.repository.get_by_idempotency_key(
                session,
                payload.idempotency_key,
            )
            if existing:
                return OrderView.model_validate(existing)

        total_amount = sum(
            (item.unit_price * item.quantity for item in payload.items),
            start=Decimal("0"),
        )
        await self.customers_service.check_credit(
            session=session,
            customer_id=payload.customer_id,
            amount=total_amount,
        )

        order_no = await self.id_generator.generate(prefix="GF")
        reservation_request = InventoryReservationRequest(
            order_no=order_no,
            items=[
                InventoryReservationItem(product_id=item.product_id, quantity=item.quantity)
                for item in payload.items
            ],
        )
        reservation = await self.inventory_service.reserve_stock(session, reservation_request)
        if reservation.insufficient_items:
            raise AppError(
                code=ErrorCode.INVENTORY_SHORTAGE,
                message="Insufficient inventory for one or more items.",
                status_code=409,
                details={
                    "items": [item.model_dump() for item in reservation.insufficient_items],
                },
            )

        order = await self.repository.create_order(
            session=session,
            order_no=order_no,
            payload=payload,
            reservation_ids=reservation.reservation_ids,
        )

        for index, item in enumerate(order.items, start=1):
            session.add(
                WorkOrderModel(
                    work_order_no=f"WO-{order.order_no}-{index:03d}",
                    order_id=order.id,
                    order_item_id=item.id,
                    process_step_key="cutting",
                    status="pending",
                    glass_type=item.glass_type,
                    specification=item.specification,
                    width_mm=item.width_mm,
                    height_mm=item.height_mm,
                    quantity=item.quantity,
                    completed_qty=0,
                    defect_qty=0,
                )
            )
        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_CREATED,
            key=order.id,
            payload={
                "order_id": order.id,
                "order_no": order.order_no,
                "status": order.status,
                "priority": order.priority,
            },
        )

        return OrderView.model_validate(order)

    async def _confirm_inventory_reservations(
        self,
        session: AsyncSession,
        order: OrderModel,
    ) -> None:
        if not order.reservation_ids:
            return

        await self.inventory_service.confirm_stock(
            session,
            order.reservation_ids,
            order_id=order.id,
        )

    async def _rebuild_inventory_reservations(
        self,
        session: AsyncSession,
        order: OrderModel,
    ) -> None:
        if order.reservation_ids:
            await self.inventory_service.release_stock(
                session,
                order.reservation_ids,
                order_id=order.id,
                release_reason="order_updated",
            )

        reservation = await self.inventory_service.reserve_stock(
            session,
            InventoryReservationRequest(
                order_no=order.order_no,
                items=[
                    InventoryReservationItem(product_id=item.product_id, quantity=item.quantity)
                    for item in order.items
                ],
            ),
        )
        if reservation.insufficient_items:
            raise AppError(
                code=ErrorCode.INVENTORY_SHORTAGE,
                message="Insufficient inventory for one or more items.",
                status_code=409,
                details={
                    "items": [item.model_dump() for item in reservation.insufficient_items],
                },
            )

        order.reservation_ids = reservation.reservation_ids
        if _order_requires_confirmed_inventory(order.status):
            await self._confirm_inventory_reservations(session, order)

    async def update_order(
        self,
        session: AsyncSession,
        order_id: str,
        payload: UpdateOrderRequest,
        actor_user_id: str,
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status in {"cancelled", "picked_up"}:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Order cannot be modified from current status.",
                status_code=409,
                details={"order_id": order_id, "status": row.status},
            )

        if payload.delivery_address is not None:
            row.delivery_address = payload.delivery_address.strip()
        if payload.expected_delivery_date is not None:
            row.expected_delivery_date = payload.expected_delivery_date
        if payload.priority is not None:
            row.priority = _normalize_priority(payload.priority)
        if payload.remark is not None:
            row.remark = payload.remark

        quantity_changed = False
        if payload.items:
            items_by_id = {item.id: item for item in row.items}
            for updated_item in payload.items:
                target = items_by_id.get(updated_item.id)
                if target is None:
                    raise AppError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="Order item does not exist.",
                        status_code=400,
                        details={"order_item_id": updated_item.id},
                    )

                if updated_item.glass_type is not None:
                    target.glass_type = updated_item.glass_type
                if updated_item.specification is not None:
                    target.specification = updated_item.specification
                if updated_item.quantity is not None:
                    quantity_changed = quantity_changed or updated_item.quantity != target.quantity
                    target.quantity = updated_item.quantity
                if updated_item.unit_price is not None:
                    target.unit_price = updated_item.unit_price
                if updated_item.process_requirements is not None:
                    target.process_requirements = updated_item.process_requirements

                target.subtotal = target.unit_price * target.quantity

        if quantity_changed and row.status not in EDITABLE_QUANTITY_ORDER_STATUSES:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Order quantity cannot change after production has started.",
                status_code=409,
                details={"order_id": order_id, "status": row.status},
            )

        work_order_result = await session.execute(
            select(WorkOrderModel).where(WorkOrderModel.order_id == row.id)
        )
        work_order_by_item_id = {
            entry.order_item_id: entry for entry in work_order_result.scalars().all()
        }
        for item in row.items:
            work_order = work_order_by_item_id.get(item.id)
            if work_order is None:
                continue
            work_order.glass_type = item.glass_type
            work_order.specification = item.specification
            work_order.width_mm = item.width_mm
            work_order.height_mm = item.height_mm
            work_order.quantity = item.quantity
            if work_order.completed_qty > work_order.quantity:
                work_order.completed_qty = work_order.quantity

        if quantity_changed:
            await self._rebuild_inventory_reservations(session, row)

        total_amount = Decimal("0")
        total_quantity = 0
        total_area_sqm = Decimal("0")
        for item in row.items:
            total_amount += item.subtotal
            total_quantity += item.quantity
            total_area_sqm += item.area_sqm * item.quantity

        row.total_amount = total_amount
        row.total_quantity = total_quantity
        row.total_area_sqm = total_area_sqm
        row.version += 1

        await session.flush()
        await session.refresh(row)

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.OPS_AUDIT_LOGGED,
            key=row.id,
            payload={
                "event": "orders.order.updated",
                "order_id": row.id,
                "order_no": row.order_no,
                "actor_user_id": actor_user_id,
                "status": row.status,
            },
        )

        return OrderView.model_validate(row)

    async def mark_entered(
        self, session: AsyncSession, order_id: str, actor_user_id: str
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status == "entered":
            return OrderView.model_validate(row)

        _ensure_order_transition(
            order_id=order_id,
            current_status=row.status,
            target_status=OrderStatus.ENTERED,
            message="Order cannot enter production from current status.",
        )

        await self._confirm_inventory_reservations(session, row)

        now = datetime.now(timezone.utc)
        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status="entered",
            confirmed_at=now,
        )
        if updated is None:
            raise order_not_found(order_id)

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_ENTERED,
            key=updated.id,
            payload={
                "order_id": updated.id,
                "order_no": updated.order_no,
                "status": updated.status,
                "actor_user_id": actor_user_id,
            },
        )

        return OrderView.model_validate(updated)

    async def approve_pickup(
        self,
        session: AsyncSession,
        order_id: str,
        actor_user_id: str,
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status == "picked_up":
            return OrderView.model_validate(row)

        if row.status == "ready_for_pickup":
            return OrderView.model_validate(row)

        _ensure_order_transition(
            order_id=order_id,
            current_status=row.status,
            target_status=OrderStatus.READY_FOR_PICKUP,
            message="Only completed orders can be approved for pickup.",
        )

        now = datetime.now(timezone.utc)
        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status="ready_for_pickup",
            pickup_approved_at=now,
            pickup_approved_by=actor_user_id,
        )
        if updated is None:
            raise order_not_found(order_id)

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_READY_FOR_PICKUP,
            key=updated.id,
            payload={
                "order_id": updated.id,
                "order_no": updated.order_no,
                "status": updated.status,
                "approved_by": actor_user_id,
                "approved_at": now.isoformat(),
            },
        )

        return OrderView.model_validate(updated)

    async def save_pickup_signature(
        self,
        session: AsyncSession,
        order_id: str,
        actor_user_id: str,
        signer_name: str,
        signature_data_url: str,
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status == "picked_up":
            return OrderView.model_validate(row)

        _ensure_order_transition(
            order_id=order_id,
            current_status=row.status,
            target_status=OrderStatus.PICKED_UP,
            message="Order is not ready for pickup signature.",
        )

        signature_bytes, extension = _decode_data_url(signature_data_url)
        now = datetime.now(timezone.utc)
        signature_key = f"orders/{order_id}/signatures/{now:%Y%m%d%H%M%S}-{uuid4().hex}.{extension}"
        storage = ObjectStorage()
        await storage.put_bytes(bucket="signatures", key=signature_key, payload=signature_bytes)

        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status="picked_up",
            picked_up_at=now,
            picked_up_by=actor_user_id,
            pickup_signer_name=signer_name.strip(),
            pickup_signature_key=signature_key,
        )
        if updated is None:
            raise order_not_found(order_id)

        shipment_result = await session.execute(
            select(ShipmentModel)
            .where(ShipmentModel.order_id == order_id)
            .order_by(ShipmentModel.created_at.desc())
            .limit(1)
        )
        shipment = shipment_result.scalar_one_or_none()
        if shipment is None:
            shipment = ShipmentModel(
                shipment_no=f"PK-{updated.order_no}",
                order_id=updated.id,
                status="delivered",
                tracking_no=updated.order_no,
                delivered_at=now,
                receiver_name=signer_name.strip(),
                signature_image=signature_key,
            )
            session.add(shipment)
        else:
            shipment.status = "delivered"
            shipment.delivered_at = now
            shipment.receiver_name = signer_name.strip()
            shipment.signature_image = signature_key

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_PICKED_UP,
            key=updated.id,
            payload={
                "order_id": updated.id,
                "order_no": updated.order_no,
                "status": updated.status,
                "signer_name": signer_name.strip(),
                "signature_key": signature_key,
                "picked_up_by": actor_user_id,
            },
        )

        return OrderView.model_validate(updated)

    async def send_pickup_email(
        self,
        session: AsyncSession,
        order_id: str,
        actor_user_id: str,
    ) -> dict:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status not in {"ready_for_pickup", "picked_up"}:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Pickup reminder can only be sent for ready or picked-up orders.",
                status_code=409,
                details={"order_id": order_id, "status": row.status},
            )

        customer_result = await session.execute(
            select(CustomerModel).where(CustomerModel.id == row.customer_id)
        )
        customer = customer_result.scalar_one_or_none()

        template_result = await session.execute(
            select(NotificationTemplateModel).where(
                NotificationTemplateModel.template_key == PICKUP_TEMPLATE_KEY
            )
        )
        template = template_result.scalar_one_or_none()
        if template is None:
            template = NotificationTemplateModel(
                template_key=PICKUP_TEMPLATE_KEY,
                name=DEFAULT_PICKUP_TEMPLATE_NAME,
                subject_template=DEFAULT_PICKUP_TEMPLATE_SUBJECT,
                body_template=DEFAULT_PICKUP_TEMPLATE_BODY,
                updated_at=datetime.now(timezone.utc),
                updated_by=actor_user_id,
            )
            session.add(template)
            await session.flush()

        first_item = row.items[0] if row.items else None
        variables = {
            "customerName": (customer.company_name if customer else row.customer_id) or "客户",
            "orderNo": row.order_no,
            "glassType": first_item.glass_type if first_item else "-",
            "specification": first_item.specification if first_item else "-",
            "quantity": str(row.total_quantity),
        }
        subject = _render_template(template.subject_template, variables)
        body = _render_template(template.body_template, variables)

        recipient = (customer.email if customer and customer.email else "").strip()
        sent_at = datetime.now(timezone.utc)
        transport = "none"
        status = "preview"
        error_message = ""
        provider_message_id = ""

        settings = get_settings()
        if not recipient:
            status = "skipped"
            error_message = "客户未填写邮箱，未实际发送。"
        elif not settings.smtp.host:
            status = "preview"
            transport = "log"
            error_message = "SMTP 未配置，邮件预览已保存。"
        else:
            from_addr = (
                settings.smtp.from_address
                or settings.smtp.user
                or "glass-factory@example.local"
            )
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = from_addr
            message["To"] = recipient
            message.set_content(body)

            try:
                if settings.smtp.secure:
                    with smtplib.SMTP_SSL(
                        settings.smtp.host,
                        settings.smtp.port,
                        timeout=10,
                    ) as smtp:
                        if settings.smtp.user and settings.smtp.password:
                            smtp.login(settings.smtp.user, settings.smtp.password)
                        smtp.send_message(message)
                else:
                    with smtplib.SMTP(
                        settings.smtp.host,
                        settings.smtp.port,
                        timeout=10,
                    ) as smtp:
                        smtp.ehlo()
                        try:
                            smtp.starttls()
                            smtp.ehlo()
                        except smtplib.SMTPException:
                            pass
                        if settings.smtp.user and settings.smtp.password:
                            smtp.login(settings.smtp.user, settings.smtp.password)
                        smtp.send_message(message)

                status = "sent"
                transport = "smtp"
                provider_message_id = f"smtp-{uuid4().hex}"
                error_message = ""
            except Exception as exc:
                status = "failed"
                transport = "smtp"
                error_message = str(exc)

        email_log = EmailLogModel(
            template_key=PICKUP_TEMPLATE_KEY,
            order_id=row.id,
            customer_email=recipient or "未填写邮箱",
            subject=subject,
            body=body,
            status=status,
            transport=transport,
            error_message=error_message,
            provider_message_id=provider_message_id,
            actor_user_id=actor_user_id,
            created_at=sent_at,
            sent_at=sent_at if status == "sent" else None,
        )
        session.add(email_log)
        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.OPS_AUDIT_LOGGED,
            key=row.id,
            payload={
                "event": "pickup_email.sent",
                "order_id": row.id,
                "order_no": row.order_no,
                "status": row.status,
                "actor_user_id": actor_user_id,
                "sent_at": sent_at.isoformat(),
                "email_status": status,
            },
        )

        return {"emailLog": _serialize_email_log(email_log, row.order_no)}

    async def upload_drawing(
        self,
        session: AsyncSession,
        order_id: str,
        filename: str,
        payload_bytes: bytes,
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        safe_name = filename.strip().replace("\\", "/").split("/")[-1] or "drawing.pdf"
        now = datetime.now(timezone.utc)
        object_key = f"orders/{order_id}/drawings/{now:%Y%m%d%H%M%S}-{uuid4().hex}-{safe_name}"

        storage = ObjectStorage()
        await storage.put_bytes(bucket="drawings", key=object_key, payload=payload_bytes)

        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status=row.status,
            drawing_object_key=object_key,
            drawing_original_name=safe_name,
        )
        if updated is None:
            raise order_not_found(order_id)

        return OrderView.model_validate(updated)

    async def apply_step_action(
        self,
        session: AsyncSession,
        order_id: str,
        step_key: str,
        action: str,
        actor_user_id: str,
        actor_role: str | None = None,
        actor_stage: str | None = None,
        piece_numbers: list[int] | None = None,
        note: str = "",
    ) -> dict:
        order = await self.repository.get_order(session, order_id)
        if order is None:
            raise order_not_found(order_id)

        normalized_step_key = _normalize_step_key(step_key)
        normalized_action = action.strip().lower()
        if normalized_action not in {"start", "complete", "rework", "acknowledge_rework"}:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Unsupported step action.",
                status_code=400,
                details={"action": action},
            )

        if resolve_canonical_role(actor_role) == "operator":
            if not actor_stage:
                raise AppError(
                    code=ErrorCode.FORBIDDEN,
                    message="Operator stage is not configured.",
                    status_code=403,
                )
            if actor_stage.strip().lower() != normalized_step_key:
                raise AppError(
                    code=ErrorCode.FORBIDDEN,
                    message="Operators can only operate orders in their own stage.",
                    status_code=403,
                    details={
                        "operator_stage": actor_stage,
                        "requested_step": normalized_step_key,
                    },
                )

        if normalized_action in {"start", "complete"} and order.status not in PRODUCTION_ACTION_ORDER_STATUSES:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Order must be entered before production actions.",
                status_code=409,
                details={"order_id": order_id, "status": order.status, "action": normalized_action},
            )

        result = await session.execute(
            select(WorkOrderModel)
            .where(WorkOrderModel.order_id == order_id)
            .order_by(WorkOrderModel.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        all_work_orders = list(result.scalars().all())
        if not all_work_orders:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="No work order found for this order.",
                status_code=404,
                details={"order_id": order_id},
            )

        stage_work_orders = [
            row for row in all_work_orders if row.process_step_key == normalized_step_key
        ]
        if not stage_work_orders and normalized_action != "acknowledge_rework":
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="No work orders are available for this process step.",
                status_code=409,
                details={"order_id": order_id, "step_key": normalized_step_key},
            )

        now = datetime.now(timezone.utc)
        outbox = OutboxPublisher(session)
        updated_work_order_ids: list[str] = []

        if normalized_action == "start":
            for row in stage_work_orders:
                if row.status not in {"pending", "in_progress"}:
                    continue
                row.status = "in_progress"
                if row.started_at is None:
                    row.started_at = now
                if normalized_step_key == "cutting":
                    row.rework_unread = False
                updated_work_order_ids.append(row.id)

                await outbox.publish_after_commit(
                    topic=Topics.PRODUCTION_STARTED,
                    key=row.id,
                    payload={
                        "order_id": order_id,
                        "work_order_id": row.id,
                        "step_key": normalized_step_key,
                        "actor_user_id": actor_user_id,
                    },
                )

            if updated_work_order_ids and order.status in {"pending", "confirmed", "entered"}:
                order.status = "in_production"
                order.version += 1
                await outbox.publish_after_commit(
                    topic=Topics.ORDER_PRODUCING,
                    key=order.id,
                    payload={
                        "order_id": order.id,
                        "order_no": order.order_no,
                        "status": order.status,
                    },
                )

        elif normalized_action == "complete":
            for row in stage_work_orders:
                if row.status not in {"pending", "in_progress", "completed"}:
                    continue

                next_step = _next_process_step(normalized_step_key)
                row.completed_qty = row.quantity
                if next_step is None:
                    row.status = "completed"
                    row.completed_at = now
                else:
                    row.status = "pending"
                    row.process_step_key = next_step
                    row.started_at = None
                    row.completed_at = None
                row.rework_unread = False
                updated_work_order_ids.append(row.id)

                await outbox.publish_after_commit(
                    topic=Topics.PRODUCTION_COMPLETED,
                    key=row.id,
                    payload={
                        "order_id": order_id,
                        "work_order_id": row.id,
                        "step_key": normalized_step_key,
                        "actor_user_id": actor_user_id,
                    },
                )

            if (
                all(
                    row.status == "completed" and row.process_step_key == "finishing"
                    for row in all_work_orders
                )
                and order.status != "completed"
            ):
                order.status = "completed"
                order.version += 1
                await outbox.publish_after_commit(
                    topic=Topics.ORDER_COMPLETED,
                    key=order.id,
                    payload={
                        "order_id": order.id,
                        "order_no": order.order_no,
                        "status": order.status,
                    },
                )
            elif updated_work_order_ids and order.status in {"pending", "confirmed", "entered"}:
                order.status = "in_production"
                order.version += 1

        elif normalized_action == "rework":
            if normalized_step_key == "cutting":
                raise AppError(
                    code=ErrorCode.ORDER_INVALID_TRANSITION,
                    message="Cutting step cannot be reworked to itself.",
                    status_code=409,
                    details={"order_id": order_id, "step_key": normalized_step_key},
                )

            normalized_pieces = sorted({piece for piece in (piece_numbers or []) if piece > 0})
            if not normalized_pieces:
                raise AppError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="piece_numbers is required for rework.",
                    status_code=400,
                )

            target = stage_work_orders[0]
            defect_qty = min(len(normalized_pieces), target.quantity)
            session.add(
                QualityCheckModel(
                    work_order_id=target.id,
                    inspector_id=actor_user_id,
                    check_type=normalized_step_key,
                    result="rework",
                    checked_qty=target.quantity,
                    passed_qty=max(target.quantity - defect_qty, 0),
                    defect_qty=defect_qty,
                    defect_details=[{"piece_no": piece_no} for piece_no in normalized_pieces],
                    remark=note.strip(),
                )
            )

            target.status = "pending"
            target.process_step_key = "cutting"
            target.rework_unread = True
            target.defect_qty += defect_qty
            target.completed_qty = max(target.completed_qty - defect_qty, 0)
            target.started_at = None
            target.completed_at = None
            updated_work_order_ids.append(target.id)

            order.status = "in_production"
            order.version += 1

            await outbox.publish_after_commit(
                topic=Topics.PRODUCTION_REWORK_REQUESTED,
                key=target.id,
                payload={
                    "order_id": order.id,
                    "order_no": order.order_no,
                    "work_order_id": target.id,
                    "step_key": normalized_step_key,
                    "piece_numbers": normalized_pieces,
                    "note": note.strip(),
                    "actor_user_id": actor_user_id,
                },
            )

        else:  # acknowledge_rework
            if normalized_step_key != "cutting":
                raise AppError(
                    code=ErrorCode.ORDER_INVALID_TRANSITION,
                    message="Only cutting step can acknowledge rework notifications.",
                    status_code=409,
                    details={"order_id": order_id, "step_key": normalized_step_key},
                )

            for row in stage_work_orders:
                if row.rework_unread:
                    row.rework_unread = False
                    updated_work_order_ids.append(row.id)

            await outbox.publish_after_commit(
                topic=Topics.PRODUCTION_REWORK_ACKNOWLEDGED,
                key=order.id,
                payload={
                    "order_id": order.id,
                    "order_no": order.order_no,
                    "step_key": normalized_step_key,
                    "actor_user_id": actor_user_id,
                },
            )

        await session.flush()

        return {
            "order_id": order.id,
            "order_no": order.order_no,
            "action": normalized_action,
            "step_key": normalized_step_key,
            "status": order.status,
            "updated_work_order_ids": updated_work_order_ids,
        }

    async def export_document_pdf(
        self,
        session: AsyncSession,
        order_id: str,
        document: str,
    ) -> bytes:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        normalized_document = document.strip().lower()
        if normalized_document not in {"order", "pickup"}:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Unsupported document type.",
                status_code=400,
                details={"document": document},
            )

        lines = [
            f"Glass Factory {normalized_document.upper()} Slip",
            f"Order No: {row.order_no}",
            f"Order ID: {row.id}",
            f"Status: {row.status}",
            f"Customer ID: {row.customer_id}",
            f"Expected Delivery: {row.expected_delivery_date.isoformat()}",
        ]

        if normalized_document == "pickup":
            lines.extend(
                [
                    f"Pickup Approved At: {row.pickup_approved_at.isoformat() if row.pickup_approved_at else '-'}",
                    f"Picked Up At: {row.picked_up_at.isoformat() if row.picked_up_at else '-'}",
                    f"Signer: {row.pickup_signer_name or '-'}",
                ]
            )

        return _build_minimal_pdf(lines)

    async def list_orders(self, session: AsyncSession, limit: int = 50) -> list[OrderView]:
        rows = await self.repository.list_orders(session, limit=limit)
        return [OrderView.model_validate(row) for row in rows]

    async def get_order(self, session: AsyncSession, order_id: str) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)
        return OrderView.model_validate(row)

    async def confirm_order(self, session: AsyncSession, order_id: str) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        if row.status == "confirmed":
            return OrderView.model_validate(row)

        _ensure_order_transition(
            order_id=order_id,
            current_status=row.status,
            target_status=OrderStatus.CONFIRMED,
            message="Order cannot be confirmed from current status.",
        )

        await self._confirm_inventory_reservations(session, row)

        now = datetime.now(timezone.utc)
        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status="confirmed",
            confirmed_at=now,
        )
        if updated is None:
            raise order_not_found(order_id)

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_CONFIRMED,
            key=updated.id,
            payload={
                "order_id": updated.id,
                "order_no": updated.order_no,
                "status": updated.status,
            },
        )

        return OrderView.model_validate(updated)

    async def cancel_order(
        self, session: AsyncSession, order_id: str, reason: str = ""
    ) -> OrderView:
        row = await self.repository.get_order(session, order_id)
        if row is None:
            raise order_not_found(order_id)

        _ensure_order_transition(
            order_id=order_id,
            current_status=row.status,
            target_status=OrderStatus.CANCELLED,
            message="Order cannot be cancelled from current status.",
        )

        await self.inventory_service.release_stock(
            session,
            row.reservation_ids,
            order_id=row.id,
            release_reason="order_cancelled",
        )

        now = datetime.now(timezone.utc)
        normalized_reason = reason.strip()
        updated = await self.repository.update_order_status(
            session,
            order_id=order_id,
            status="cancelled",
            cancelled_at=now,
            cancelled_reason=normalized_reason,
        )
        if updated is None:
            raise order_not_found(order_id)

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.ORDER_CANCELLED,
            key=updated.id,
            payload={
                "order_id": updated.id,
                "order_no": updated.order_no,
                "status": updated.status,
                "reason": normalized_reason,
            },
        )

        return OrderView.model_validate(updated)

    async def get_timeline(self, session: AsyncSession, order_id: str) -> list[OrderTimelineEvent]:
        order = await self.repository.get_order(session, order_id)
        if order is None:
            raise order_not_found(order_id)

        timeline: list[OrderTimelineEvent] = [
            OrderTimelineEvent(
                event="orders.order.created",
                created_at=order.created_at,
                status="created",
                details={"order_no": order.order_no},
            )
        ]

        if order.confirmed_at is not None:
            timeline.append(
                OrderTimelineEvent(
                    event="orders.order.confirmed",
                    created_at=order.confirmed_at,
                    status="confirmed",
                )
            )

        if order.cancelled_at is not None:
            timeline.append(
                OrderTimelineEvent(
                    event="orders.order.cancelled",
                    created_at=order.cancelled_at,
                    status="cancelled",
                    details={"reason": order.cancelled_reason or ""},
                )
            )

        event_rows = await session.execute(
            select(EventOutboxModel)
            .where(EventOutboxModel.event_key == order_id)
            .order_by(EventOutboxModel.created_at.asc())
        )

        for event in event_rows.scalars().all():
            timeline.append(
                OrderTimelineEvent(
                    event=event.topic,
                    created_at=event.created_at,
                    status=event.status,
                    details={
                        "payload": event.payload,
                        "attempt_count": event.attempt_count,
                        "last_error": event.last_error,
                    },
                )
            )

        timeline.sort(key=lambda item: item.created_at)
        return timeline
