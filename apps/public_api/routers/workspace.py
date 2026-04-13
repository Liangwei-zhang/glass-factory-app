from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.schema import UpdateCustomerRequest
from domains.customers.service import CustomersService
from domains.inventory.service import InventoryService
from domains.notifications.service import NotificationsService
from domains.orders.schema import PickupSignatureRequest
from domains.workspace import finance_support as workspace_finance
from domains.workspace import logistics_support as workspace_logistics
from domains.workspace import orders_support as workspace_orders
from domains.workspace import session_support as workspace_session
from domains.workspace import settings_support as workspace_settings
from domains.workspace import ui_support as workspace_ui
from infra.core.errors import AppError
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key
from infra.security.identity import resolve_canonical_role
from infra.security.rbac import require_roles

router = APIRouter(prefix="/workspace", tags=["workspace"])
workspace_guard = require_roles(["operator", "manager", "admin"])
customers_service = CustomersService()
notifications_service = NotificationsService()
inventory_service = InventoryService()


def _assert_workspace_office_or_manager(
    auth_user: AuthUser,
    detail: str = "当前角色无权执行此操作。",
) -> None:
    canonical_role = resolve_canonical_role(auth_user.role)
    if canonical_role in {"manager", "admin", "super_admin"}:
        return
    if canonical_role == "operator" and not auth_user.stage:
        return
    raise HTTPException(status_code=403, detail=detail)


def _assert_workspace_worker_or_manager(
    auth_user: AuthUser,
    detail: str = "当前角色无权执行此操作。",
) -> None:
    canonical_role = resolve_canonical_role(auth_user.role)
    if canonical_role in {"manager", "admin", "super_admin"}:
        return
    if canonical_role == "operator" and auth_user.stage:
        return
    raise HTTPException(status_code=403, detail=detail)


def _workspace_customer_create_fields(payload: dict[str, Any]) -> dict[str, str | None]:
    return {
        "company_name": str(payload.get("companyName") or ""),
        "contact_name": str(payload.get("contactName") or "").strip() or None,
        "phone": str(payload.get("phone") or "").strip() or None,
        "email": str(payload.get("email") or "").strip() or None,
        "address": str(payload.get("notes") or "").strip() or None,
    }


def _workspace_customer_update_request(payload: dict[str, Any]) -> UpdateCustomerRequest:
    mapped_payload: dict[str, Any] = {}
    if "companyName" in payload:
        mapped_payload["company_name"] = payload.get("companyName")
    if "contactName" in payload:
        mapped_payload["contact_name"] = payload.get("contactName")
    if "phone" in payload:
        mapped_payload["phone"] = payload.get("phone")
    if "email" in payload:
        mapped_payload["email"] = payload.get("email")
    if "notes" in payload:
        mapped_payload["address"] = payload.get("notes")
    if "creditLimit" in payload and payload.get("creditLimit") is not None:
        from decimal import Decimal as _Decimal
        mapped_payload["credit_limit"] = _Decimal(str(payload["creditLimit"]))
    return UpdateCustomerRequest(**mapped_payload)


async def _enforce_workspace_idempotency(namespace: str, idempotency_key: str | None) -> str:
    return await enforce_idempotency_key(f"workspace:{namespace}", idempotency_key)


@router.post("/auth/login")
async def workspace_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    await _enforce_workspace_idempotency("auth:login", idempotency_key)
    try:
        return await workspace_session.login_workspace_user(session, payload)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/me")
async def workspace_me(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return await workspace_session.build_workspace_me(session, auth_user)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/bootstrap")
async def workspace_bootstrap(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        return await workspace_session.build_workspace_bootstrap(session, auth_user)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/customers")
async def workspace_list_customers(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ = auth_user
    return {"customers": await workspace_ui.serialize_customers(session)}


@router.post("/customers")
async def workspace_create_customer(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("customers:create", idempotency_key)

    try:
        customer = await customers_service.create_workspace_customer(
            session,
            **_workspace_customer_create_fields(payload),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "customer": workspace_ui.serialize_customer(customer),
        "customers": await workspace_ui.serialize_customers(session),
    }


@router.patch("/customers/{customer_id}")
async def workspace_update_customer(
    customer_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("customers:update", idempotency_key)

    try:
        customer = await customers_service.update_customer(
            session,
            customer_id,
            _workspace_customer_update_request(payload),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "customer": workspace_ui.serialize_customer(customer),
        "customers": await workspace_ui.serialize_customers(session),
    }


@router.get("/orders")
async def workspace_list_orders(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ = auth_user
    try:
        return {"orders": await workspace_orders.list_workspace_orders(session)}
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/orders/{order_id}")
async def workspace_get_order(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ = auth_user
    try:
        return await workspace_orders.get_workspace_order(session, order_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/orders/{order_id}/drawing")
async def workspace_download_drawing(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    _ = auth_user
    try:
        local_path, filename = await workspace_orders.get_order_drawing_file(session, order_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path=local_path, filename=filename)


@router.get("/orders/{order_id}/pickup-signature")
async def workspace_download_pickup_signature(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    _ = auth_user
    try:
        local_path, filename = await workspace_orders.get_order_pickup_signature_file(
            session,
            order_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path=local_path, filename=filename)


@router.get("/orders/{order_id}/export")
async def workspace_export_order(
    order_id: str,
    document: str = Query(default="order"),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _ = auth_user
    try:
        payload = await workspace_orders.export_workspace_order_document(
            session,
            order_id,
            document=document,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{order_id}-{document}.pdf"'},
    )


@router.post("/orders")
async def workspace_create_order(
    customerId: str = Form(...),
    glassType: str | None = Form(default=None),
    thickness: str | None = Form(default=None),
    quantity: int | None = Form(default=None),
    priority: str = Form("normal"),
    estimatedCompletionDate: str | None = Form(None),
    specialInstructions: str = Form(""),
    itemsJson: str | None = Form(default=None),
    drawing: UploadFile | None = File(default=None),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    effective_idempotency_key = await _enforce_workspace_idempotency(
        "orders:create",
        idempotency_key,
    )

    try:
        return await workspace_orders.create_workspace_order(
            session,
            customer_id=customerId,
            glass_type=glassType,
            thickness=thickness,
            quantity=quantity,
            priority=priority,
            estimated_completion_date=estimatedCompletionDate,
            special_instructions=specialInstructions,
            items_json=itemsJson,
            drawing=drawing,
            idempotency_key=effective_idempotency_key,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put("/orders/{order_id}")
async def workspace_update_order(
    order_id: str,
    glassType: str | None = Form(default=None),
    thickness: str | None = Form(default=None),
    quantity: int | None = Form(default=None),
    priority: str | None = Form(default=None),
    estimatedCompletionDate: str | None = Form(default=None),
    specialInstructions: str | None = Form(default=None),
    drawing: UploadFile | None = File(default=None),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:update", idempotency_key)

    try:
        return await workspace_orders.update_workspace_order(
            session,
            order_id=order_id,
            glass_type=glassType,
            thickness=thickness,
            quantity=quantity,
            priority=priority,
            estimated_completion_date=estimatedCompletionDate,
            special_instructions=specialInstructions,
            drawing=drawing,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/cancel")
async def workspace_cancel_order(
    order_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:cancel", idempotency_key)

    try:
        return await workspace_orders.cancel_workspace_order(
            session,
            order_id=order_id,
            reason=str(payload.get("reason") or ""),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/entered")
async def workspace_mark_entered(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:entered", idempotency_key)

    try:
        return await workspace_orders.mark_workspace_order_entered(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/steps/{step_key}")
async def workspace_step_action(
    order_id: str,
    step_key: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_worker_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:step-action", idempotency_key)

    try:
        return await workspace_orders.apply_workspace_step_action(
            session,
            order_id=order_id,
            step_key=step_key,
            payload=payload,
            actor_user_id=auth_user.user_id,
            actor_role=auth_user.role,
            actor_stage=auth_user.stage,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/pickup/approve")
async def workspace_pickup_approve(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    canonical_role = resolve_canonical_role(auth_user.role)
    if canonical_role not in {"manager", "admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="当前角色无权执行此操作。")
    await _enforce_workspace_idempotency("orders:pickup-approve", idempotency_key)

    try:
        return await workspace_orders.approve_workspace_pickup(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/pickup/send-email")
async def workspace_pickup_send_email(
    order_id: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:pickup-send-email", idempotency_key)

    try:
        return await workspace_orders.send_workspace_pickup_email(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/pickup/signature")
async def workspace_pickup_signature(
    order_id: str,
    payload: PickupSignatureRequest,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("orders:pickup-signature", idempotency_key)

    try:
        return await workspace_orders.save_workspace_pickup_signature(
            session,
            order_id=order_id,
            signer_name=payload.signer_name,
            signature_data_url=payload.signature_data_url,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/shipments")
async def workspace_list_shipments(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    return {
        "shipments": await workspace_logistics.list_workspace_shipments(
            session,
            limit=limit,
            status=status,
            order_id=order_id,
        )
    }


@router.post("/orders/{order_id}/shipment")
async def workspace_create_shipment(
    order_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("shipments:create", idempotency_key)

    try:
        return await workspace_logistics.create_workspace_shipment(
            session,
            order_id=order_id,
            carrier_name=str(payload.get("carrierName") or "") or None,
            tracking_no=str(payload.get("trackingNo") or "") or None,
            vehicle_no=str(payload.get("vehicleNo") or "") or None,
            driver_name=str(payload.get("driverName") or "") or None,
            driver_phone=str(payload.get("driverPhone") or "") or None,
            shipped_at=payload.get("shippedAt"),
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/shipments/{shipment_id}/deliver")
async def workspace_deliver_shipment(
    shipment_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("shipments:deliver", idempotency_key)

    try:
        return await workspace_logistics.deliver_workspace_shipment(
            session,
            shipment_id=shipment_id,
            receiver_name=str(payload.get("receiverName") or ""),
            receiver_phone=str(payload.get("receiverPhone") or "") or None,
            delivered_at=payload.get("deliveredAt"),
            signature_data_url=str(payload.get("signatureDataUrl") or "") or None,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/receivables")
async def workspace_list_receivables(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    return {
        "receivables": await workspace_finance.list_workspace_receivables(
            session,
            limit=limit,
            status=status,
            customer_id=customer_id,
        )
    }


@router.post("/orders/{order_id}/receivable")
async def workspace_create_receivable(
    order_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("receivables:create", idempotency_key)

    try:
        return await workspace_finance.create_workspace_receivable(
            session,
            order_id=order_id,
            due_date=payload.get("dueDate"),
            amount=payload.get("amount"),
            invoice_no=str(payload.get("invoiceNo") or "") or None,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/receivables/{receivable_id}/payments")
async def workspace_record_receivable_payment(
    receivable_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("receivables:payments", idempotency_key)

    try:
        return await workspace_finance.record_workspace_payment(
            session,
            receivable_id=receivable_id,
            amount=payload.get("amount"),
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/receivables/{receivable_id}/refunds")
async def workspace_record_receivable_refund(
    receivable_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("receivables:refunds", idempotency_key)

    try:
        return await workspace_finance.record_workspace_refund(
            session,
            receivable_id=receivable_id,
            amount=payload.get("amount"),
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/notifications")
async def workspace_notifications(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return {"notifications": await workspace_ui.serialize_notifications(session, auth_user.user_id)}


@router.post("/notifications/read")
async def workspace_mark_notifications_read(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    await _enforce_workspace_idempotency("notifications:mark-read", idempotency_key)
    await notifications_service.mark_notifications_read(session, auth_user.user_id)
    return {"notifications": await workspace_ui.serialize_notifications(session, auth_user.user_id)}


@router.get("/settings/glass-types")
async def workspace_list_glass_types(
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user, detail="当前角色无权访问玻璃类型配置。")
    return {"glassTypes": await workspace_settings.list_glass_types(session, auth_user.user_id)}


@router.post("/settings/glass-types")
async def workspace_create_glass_type(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("settings:glass-types:create", idempotency_key)

    try:
        glass_type = await workspace_settings.create_glass_type(
            session,
            name=str(payload.get("name") or ""),
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "glassType": workspace_settings.serialize_glass_type(glass_type),
        "glassTypes": await workspace_settings.list_glass_types(session),
    }


@router.patch("/settings/glass-types/{glass_type_id}")
async def workspace_update_glass_type(
    glass_type_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("settings:glass-types:update", idempotency_key)

    try:
        glass_type = await workspace_settings.update_glass_type(
            session,
            glass_type_id,
            name=str(payload.get("name") or "") if "name" in payload else None,
            is_active=bool(payload.get("isActive")) if "isActive" in payload else None,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "glassType": workspace_settings.serialize_glass_type(glass_type),
        "glassTypes": await workspace_settings.list_glass_types(session),
    }


@router.get("/settings/notification-templates/{template_key}")
async def workspace_get_notification_template(
    template_key: str,
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)

    try:
        template = await workspace_settings.get_notification_template(
            session,
            template_key,
            auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {"template": template}


@router.put("/settings/notification-templates/{template_key}")
async def workspace_update_notification_template(
    template_key: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    await _enforce_workspace_idempotency("settings:notification-template:update", idempotency_key)

    try:
        template = await workspace_settings.update_notification_template(
            session,
            template_key,
            subject_template=str(payload.get("subjectTemplate") or ""),
            body_template=str(payload.get("bodyTemplate") or ""),
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {"template": template}


@router.get("/email-logs")
async def workspace_email_logs(
    limit: int = Query(default=20, ge=1, le=100),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user)
    return {"logs": await workspace_settings.list_email_logs(session, limit=limit)}


@router.post("/inventory/adjustments")
async def workspace_adjust_inventory(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(workspace_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _assert_workspace_office_or_manager(auth_user, detail="当前角色无权执行库存调整。")
    await _enforce_workspace_idempotency("inventory:adjustments", idempotency_key)

    raw_quantity = payload.get("quantity")
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="数量必须是正整数。") from None

    product_id = str(payload.get("productId") or payload.get("sku") or "").strip()
    direction = str(payload.get("direction") or "").strip().lower()
    reason = str(payload.get("reason") or payload.get("remark") or "")
    reference_no = str(payload.get("referenceNo") or payload.get("refNo") or "") or None

    if not product_id:
        raise HTTPException(status_code=400, detail="请选择需要调整的物料。")

    try:
        snapshot = await inventory_service.adjust_stock(
            session,
            product_id=product_id,
            direction=direction,
            quantity=quantity,
            actor_user_id=auth_user.user_id,
            reason=reason,
            reference_no=reference_no,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {"inventory": snapshot.model_dump(mode="json")}
