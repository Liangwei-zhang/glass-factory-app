class Topics:
    ORDER_CREATED = "orders.order.created"
    ORDER_CONFIRMED = "orders.order.confirmed"
    ORDER_ENTERED = "orders.order.entered"
    ORDER_PRODUCING = "orders.order.producing"
    ORDER_PRODUCED = "orders.order.produced"
    ORDER_SHIPPING = "orders.order.shipping"
    ORDER_DELIVERED = "orders.order.delivered"
    ORDER_COMPLETED = "orders.order.completed"
    ORDER_READY_FOR_PICKUP = "orders.order.ready_for_pickup"
    ORDER_PICKED_UP = "orders.order.picked_up"
    ORDER_CANCELLED = "orders.order.cancelled"

    INVENTORY_RESERVED = "inventory.stock.reserved"
    INVENTORY_DEDUCTED = "inventory.stock.deducted"
    INVENTORY_ROLLED_BACK = "inventory.stock.rolled_back"
    INVENTORY_LOW_STOCK = "inventory.stock.low_stock_alert"

    PRODUCTION_SCHEDULED = "production.work_order.scheduled"
    PRODUCTION_STARTED = "production.work_order.started"
    PRODUCTION_COMPLETED = "production.work_order.completed"
    PRODUCTION_REWORK_REQUESTED = "production.work_order.rework_requested"
    PRODUCTION_REWORK_ACKNOWLEDGED = "production.work_order.rework_acknowledged"

    LOGISTICS_SHIPPED = "logistics.shipment.shipped"
    LOGISTICS_DELIVERED = "logistics.shipment.delivered"

    FINANCE_INVOICE_CREATED = "finance.invoice.created"
    FINANCE_PAYMENT_RECEIVED = "finance.payment.received"
    FINANCE_PAYMENT_REFUNDED = "finance.payment.refunded"

    OPS_AUDIT_LOGGED = "ops.audit.logged"
