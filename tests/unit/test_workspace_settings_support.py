from __future__ import annotations

from datetime import datetime, timezone

from domains.workspace import settings_support
from infra.db.models.settings import EmailLogModel, GlassTypeModel, NotificationTemplateModel


def test_settings_support_serializers_map_workspace_payloads() -> None:
    now = datetime.now(timezone.utc)
    glass_type = GlassTypeModel(
        id="glass-1",
        name="Clear",
        is_active=True,
        sort_order=2,
        updated_at=now,
    )
    template = NotificationTemplateModel(
        template_key=settings_support.PICKUP_TEMPLATE_KEY,
        name="Ready for Pickup 邮件",
        subject_template="订单 {{orderNo}} 已可取货",
        body_template="正文",
        updated_at=now,
    )
    log = EmailLogModel(
        id="log-1",
        template_key=settings_support.PICKUP_TEMPLATE_KEY,
        order_id="order-1",
        customer_email="demo@example.com",
        subject="subject",
        body="body",
        status="preview",
        transport="log",
        error_message="",
        provider_message_id="provider-1",
        created_at=now,
        sent_at=None,
    )

    assert settings_support.serialize_glass_type(glass_type)["name"] == "Clear"
    assert settings_support.serialize_notification_template(template, "Ops")["updatedByName"] == "Ops"
    assert settings_support.serialize_email_log(log, "GF-001")["orderNo"] == "GF-001"