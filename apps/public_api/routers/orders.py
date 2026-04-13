from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Header,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from domains.orders.schema import (
    CancelOrderRequest,
    CreateOrderItem,
    CreateOrderRequest,
    CustomerCreateOrderRequest,
    OrderTimelineEvent,
    OrderView,
    PickupSignatureRequest,
    StepActionRequest,
    UpdateOrderRequest,
)
from domains.orders.service import OrdersService
from domains.workspace import ui_support as workspace_ui
from infra.core.errors import AppError, ErrorCode
from infra.db.models.customers import CustomerModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key
from infra.security.identity import resolve_canonical_role
from infra.security.rate_limit import limiter
from infra.security.rbac import require_roles, require_scopes
from infra.storage.object_storage import ObjectStorage

router = APIRouter(prefix="/orders", tags=["orders"])
service = OrdersService()
operator_guard = require_roles(["operator", "manager", "admin"])
operator_write_guard = require_scopes(["orders:write"])
stage_operator_guard = require_scopes(["production:write"])
manager_guard = require_roles(["manager", "admin"])


async def _normalize_customer_create_order_payload(
    session: AsyncSession,
    user: AuthUser,
    payload: CustomerCreateOrderRequest,
    effective_idempotency_key: str,
) -> CreateOrderRequest:
    customer_id = (user.customer_id or "").strip()
    if not customer_id:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Customer identity is missing from access token.",
            status_code=401,
        )

    customer = await session.get(CustomerModel, customer_id)
    if customer is None:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Customer identity is invalid.",
            status_code=401,
            details={"customer_id": customer_id},
        )

    product = await workspace_ui.ensure_product_inventory(
        session,
        payload.glass_type,
        payload.thickness,
        payload.quantity,
    )
    return CreateOrderRequest(
        customer_id=customer.id,
        delivery_address=customer.address or "factory-pickup",
        expected_delivery_date=workspace_ui.parse_date_input(payload.estimated_completion_date),
        priority=payload.priority,
        remark=payload.special_instructions,
        idempotency_key=effective_idempotency_key,
        items=[
            CreateOrderItem(
                product_id=product.id,
                product_name=product.product_name,
                glass_type=payload.glass_type.strip() or "Clear",
                specification=payload.thickness.strip() or "6mm",
                width_mm=1000,
                height_mm=1000,
                quantity=payload.quantity,
                unit_price="1.00",
                process_requirements=payload.special_instructions,
            )
        ],
    )


@router.post("", response_model=OrderView, status_code=201)
@limiter.limit("10/minute")
async def create_order(
    request: Request,
    payload: CreateOrderRequest | CustomerCreateOrderRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = request
    request_idempotency_key = getattr(payload, "idempotency_key", None)
    effective_idempotency_key = request_idempotency_key or idempotency_key
    effective_idempotency_key = await enforce_idempotency_key(
        "orders:create",
        effective_idempotency_key,
    )

    if isinstance(payload, CustomerCreateOrderRequest):
        payload = await _normalize_customer_create_order_payload(
            session,
            user,
            payload,
            effective_idempotency_key,
        )
    else:
        payload = payload.model_copy(update={"idempotency_key": effective_idempotency_key})

    if resolve_canonical_role(user.role) == "customer" and payload.customer_id != (
        user.customer_id or payload.customer_id
    ):
        payload = payload.model_copy(
            update={"customer_id": user.customer_id or payload.customer_id}
        )

    return await service.create_order(session, payload)


@router.get("", response_model=list[OrderView])
async def list_orders(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> list[OrderView]:
    _ = user
    return await service.list_orders(session, limit=limit)


@router.get("/{order_id}", response_model=OrderView)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> OrderView:
    _ = user
    return await service.get_order(session, order_id)


@router.put("/{order_id}", response_model=OrderView)
@limiter.limit("30/minute")
async def update_order(
    request: Request,
    order_id: str,
    payload: UpdateOrderRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = request
    await enforce_idempotency_key("orders:update", idempotency_key)
    return await service.update_order(
        session,
        order_id=order_id,
        payload=payload,
        actor_user_id=user.user_id,
    )


@router.put("/{order_id}/cancel", response_model=OrderView)
async def cancel_order(
    order_id: str,
    payload: CancelOrderRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = user
    await enforce_idempotency_key("orders:cancel", idempotency_key)
    return await service.cancel_order(session, order_id, reason=payload.reason)


@router.post("/{order_id}/cancel", response_model=OrderView)
async def cancel_order_alias(
    order_id: str,
    payload: CancelOrderRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = user
    await enforce_idempotency_key("orders:cancel", idempotency_key)
    return await service.cancel_order(session, order_id, reason=payload.reason)


@router.put("/{order_id}/confirm", response_model=OrderView)
async def confirm_order(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = user
    await enforce_idempotency_key("orders:confirm", idempotency_key)
    return await service.confirm_order(session, order_id)


@router.post("/{order_id}/entered", response_model=OrderView)
async def mark_order_entered(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    await enforce_idempotency_key("orders:entered", idempotency_key)
    return await service.mark_entered(session, order_id, actor_user_id=user.user_id)


@router.post("/{order_id}/pickup/approve", response_model=OrderView)
async def approve_pickup(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(manager_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    await enforce_idempotency_key("orders:pickup-approve", idempotency_key)
    return await service.approve_pickup(session, order_id, actor_user_id=user.user_id)


@router.post("/{order_id}/pickup/signature", response_model=OrderView)
async def submit_pickup_signature(
    order_id: str,
    payload: PickupSignatureRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    await enforce_idempotency_key("orders:pickup-signature", idempotency_key)
    return await service.save_pickup_signature(
        session,
        order_id,
        actor_user_id=user.user_id,
        signer_name=payload.signer_name,
        signature_data_url=payload.signature_data_url,
    )


@router.post("/{order_id}/pickup/send-email")
async def send_pickup_email(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    await enforce_idempotency_key("orders:pickup-send-email", idempotency_key)
    return await service.send_pickup_email(session, order_id, actor_user_id=user.user_id)


@router.post("/{order_id}/steps/{step_key}")
@limiter.limit("60/minute")
async def apply_step_action(
    request: Request,
    order_id: str,
    step_key: str = Path(...),
    payload: StepActionRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(stage_operator_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    _ = request
    await enforce_idempotency_key("orders:step-action", idempotency_key)
    request_payload = payload or StepActionRequest(action="start")
    return await service.apply_step_action(
        session,
        order_id=order_id,
        step_key=step_key,
        action=request_payload.action,
        actor_user_id=user.user_id,
        actor_role=user.role,
        actor_stage=user.stage,
        piece_numbers=request_payload.piece_numbers,
        note=request_payload.note,
    )


@router.post("/{order_id}/drawing", response_model=OrderView)
async def upload_order_drawing(
    order_id: str,
    drawing: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OrderView:
    _ = user
    await enforce_idempotency_key("orders:upload-drawing", idempotency_key)
    payload = await drawing.read()
    if not payload:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Drawing file is empty.",
            status_code=400,
        )

    return await service.upload_drawing(
        session,
        order_id=order_id,
        filename=drawing.filename or "drawing.pdf",
        payload_bytes=payload,
    )


@router.get("/{order_id}/drawing")
async def download_order_drawing(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> FileResponse:
    _ = user
    order = await service.get_order(session, order_id)
    if not order.drawing_object_key:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Drawing file is not uploaded.",
            status_code=404,
            details={"order_id": order_id},
        )

    storage = ObjectStorage()
    if not await storage.exists(bucket="drawings", key=order.drawing_object_key):
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Drawing file is not found in storage.",
            status_code=404,
            details={"order_id": order_id},
        )
    local_path = await storage.get_downloadable_path(
        bucket="drawings",
        key=order.drawing_object_key,
    )

    return FileResponse(
        path=local_path,
        filename=order.drawing_original_name or "drawing.pdf",
    )


@router.get("/{order_id}/export")
async def export_order_document(
    order_id: str,
    document: str = Query(default="order"),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> Response:
    _ = user
    pdf_bytes = await service.export_document_pdf(session, order_id=order_id, document=document)
    filename = f"{order_id}-{document}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{order_id}/timeline", response_model=list[OrderTimelineEvent])
async def order_timeline(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> list[OrderTimelineEvent]:
    _ = user
    return await service.get_timeline(session, order_id)
