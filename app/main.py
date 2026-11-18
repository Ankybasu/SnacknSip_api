
from datetime import datetime, time, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .supabase_client import supabase
from .schemas import OrderCreate, MenuItemCreate


app = FastAPI(title="Snack 'n' Sip API", version="1.0.0")

# India Standard Time (UTC+5:30).
IST = timezone(timedelta(hours=5, minutes=30))


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip()
        for x in settings.cors_origins.split(",")
        if x.strip()
    ] + ["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def rows(table: str):
    """Fetch all rows from a Supabase table using pagination."""
    result = []
    page_size = 500
    start = 0

    while True:
        response = (
            supabase.table(table)
            .select("*")
            .range(start, start + page_size - 1)
            .execute()
        )

        batch = response.data or []
        result.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return result


def parse_created_at(value: str) -> datetime:
    """Convert a Supabase timestamp into an aware datetime."""
    created = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    return created


@app.get("/")
def home():
    return {
        "message": "Snack 'n' Sip API is running successfully!"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- MENU ----------------

@app.get("/api/menu")
def get_menu():
    return (
        supabase.table("menu_items")
        .select("*")
        .order("category")
        .order("name")
        .execute()
        .data
    )


@app.post("/api/menu")
def add_menu_item(payload: MenuItemCreate):
    result = (
        supabase.table("menu_items")
        .insert(payload.model_dump())
        .execute()
    )

    return result.data[0] if result.data else {}


# ---------------- CREATE ORDER ----------------

@app.post("/api/orders")
def create_order(payload: OrderCreate):

    menu_items = {
        item["id"]: item
        for item in rows("menu_items")
    }

    order_lines = []
    total = 0.0

    for requested in payload.items:

        item = menu_items.get(requested.menu_item_id)

        if not item or not item.get("is_available", True):
            raise HTTPException(
                status_code=400,
                detail=f"Menu item unavailable: {requested.menu_item_id}"
            )

        unit_price = float(item["price"])
        line_total = round(unit_price * requested.quantity, 2)

        total += line_total

        order_lines.append({
            "menu_item_id": item["id"],
            "item_name": item["name"],
            "quantity": requested.quantity,
            "unit_price": unit_price,
            "line_total": line_total
        })

    order_result = (
        supabase.table("orders")
        .insert({
            "customer_name": payload.customer_name,
            "customer_phone": payload.customer_phone,
            "total_amount": round(total, 2),
            "notes": payload.notes,
            "status": "completed"
        })
        .execute()
    )

    if not order_result.data:
        raise HTTPException(
            status_code=500,
            detail="Could not create order"
        )

    order = order_result.data[0]

    for line in order_lines:
        line["order_id"] = order["id"]

    try:
        supabase.table("order_items").insert(order_lines).execute()
    except Exception as exc:
        # Compensating cleanup if item insertion fails.
        supabase.table("orders").delete().eq(
            "id", order["id"]
        ).execute()

        raise HTTPException(
            status_code=500,
            detail="Order items could not be saved"
        ) from exc

    return {
        "order": order,
        "items": order_lines
    }


# ---------------- ORDER HISTORY ----------------

@app.get("/api/orders")
def get_orders(limit: int = 100):

    return (
        supabase.table("orders")
        .select("*")
        .order("created_at", desc=True)
        .limit(min(max(limit, 1), 500))
        .execute()
        .data
    )


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):

    order = (
        supabase.table("orders")
        .select("*")
        .eq("id", order_id)
        .maybe_single()
        .execute()
        .data
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    items = (
        supabase.table("order_items")
        .select("*")
        .eq("order_id", order_id)
        .execute()
        .data
    )

    return {
        "order": order,
        "items": items
    }


# ---------------- PERMANENT DELETE ----------------

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str):

    existing = (
        supabase.table("orders")
        .select("id")
        .eq("id", order_id)
        .maybe_single()
        .execute()
        .data
    )

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    try:
        # Delete associated order items first.
        supabase.table("order_items").delete().eq(
            "order_id", order_id
        ).execute()

        # Then permanently delete the order.
        supabase.table("orders").delete().eq(
            "id", order_id
        ).execute()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not delete order from database"
        ) from exc

    return {
        "success": True,
        "message": "Order permanently deleted",
        "order_id": order_id
    }


# ---------------- SALES SUMMARY ----------------

@app.get("/api/sales/summary")
def sales_summary():

    now_ist = datetime.now(IST)

    today_start_ist = datetime.combine(
        now_ist.date(),
        time.min
    ).replace(tzinfo=IST)

    tomorrow_start_ist = today_start_ist + timedelta(days=1)

    month_start_ist = datetime(
        now_ist.year,
        now_ist.month,
        1,
        tzinfo=IST
    )

    # Convert local calendar boundaries to UTC for comparison.
    today_start_utc = today_start_ist.astimezone(timezone.utc)
    tomorrow_start_utc = tomorrow_start_ist.astimezone(timezone.utc)
    month_start_utc = month_start_ist.astimezone(timezone.utc)

    all_orders = rows("orders")

    today_orders = []
    monthly_orders = []

    for order in all_orders:

        created_value = order.get("created_at")

        if not created_value:
            continue

        created = parse_created_at(created_value)

        if today_start_utc <= created < tomorrow_start_utc:
            today_orders.append(order)

        if month_start_utc <= created < tomorrow_start_utc:
            monthly_orders.append(order)

    def calculate_total(order_list):
        return round(
            sum(
                float(order.get("total_amount") or 0)
                for order in order_list
            ),
            2
        )

    return {
        "today_sales": calculate_total(today_orders),
        "today_orders": len(today_orders),

        "monthly_sales": calculate_total(monthly_orders),
        "monthly_orders": len(monthly_orders),

        "overall_sales": calculate_total(all_orders),
        "overall_orders": len(all_orders)
    }
