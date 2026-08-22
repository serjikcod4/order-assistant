from datetime import datetime
from decimal import Decimal

from order_assistant.domain import Brand, InventoryItem, OrderRequirements


demo_requirements = OrderRequirements(
    model="6204",
    quantity=500,
    primary_brand=Brand.SKF,
    fallback_brands=[Brand.FAG],
    max_unit_price=Decimal("250"),
    delivery_deadline=datetime(2026, 8, 15, 9, 0),
)

demo_inventory = [
    InventoryItem(
        sku="SKU-21",
        brand=Brand.SKF,
        model="6204",
        stock=300,
        unit_price=Decimal("230"),
        delivery_available_at=datetime(2026, 8, 15, 8, 0),
    ),
    InventoryItem(
        sku="SKU-22",
        brand=Brand.SKF,
        model="6204",
        stock=400,
        unit_price=Decimal("270"),
        delivery_available_at=datetime(2026, 8, 15, 8, 0),
    ),
    InventoryItem(
        sku="SKU-23",
        brand=Brand.FAG,
        model="6204",
        stock=600,
        unit_price=Decimal("240"),
        delivery_available_at=datetime(2026, 8, 15, 8, 30),
    ),
    InventoryItem(
        sku="SKU-24",
        brand=Brand.NSK,
        model="6204",
        stock=1000,
        unit_price=Decimal("190"),
        delivery_available_at=datetime(2026, 8, 15, 7, 0),
    ),
]
