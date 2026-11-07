import json
import asyncio
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from config import ORDERS_FILE, SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger("sendflowers.database")

# Initialize Supabase client if credentials are configured
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase_client: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Successfully connected to Supabase Database (%s)", SUPABASE_URL)
    except Exception as exc:
        logger.error("Failed to initialize Supabase client: %s. Falling back to local JSON file.", exc)
        supabase_client = None
else:
    logger.info("Supabase credentials not configured. Using local JSON store at: %s", ORDERS_FILE)

# Local JSON Lock
_lock = asyncio.Lock()

def _ensure_file():
    """Ensure the orders storage file exists and is initialized."""
    if not ORDERS_FILE.exists():
        logger.info("Database file not found. Initializing new orders file at: %s", ORDERS_FILE)
        ORDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)

def _read_orders_sync() -> List[Dict[str, Any]]:
    """Synchronously read and parse orders from disk."""
    _ensure_file()
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [o for o in data if isinstance(o, dict) and o.get("order_id")]
            return []
    except Exception as exc:
        logger.error("Error reading %s: %s", ORDERS_FILE, exc)
        return []

def _write_orders_sync(orders: List[Dict[str, Any]]):
    """Atomically write orders to disk using a temporary file replacement."""
    _ensure_file()
    temp_file = ORDERS_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(orders, f, indent=2, ensure_ascii=False)
        temp_file.replace(ORDERS_FILE)
    except Exception as exc:
        logger.error("Failed to write orders to %s: %s", ORDERS_FILE, exc)
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        raise

def _prepare_supabase_row(order: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a full, structured row dictionary for Supabase."""
    details = order.get("details") or {}
    email_val = order.get("email") or details.get("email")
    if email_val:
        email_val = str(email_val).strip() or None
    else:
        email_val = None

    device_id = order.get("device_id") or details.get("deviceId") or None
    sender_name = order.get("sender_name") or details.get("senderName") or None
    recipient_name = order.get("recipient_name") or details.get("recipientName") or None
    message = order.get("message") or details.get("message") or None
    language = order.get("language") or details.get("language") or "en"
    delivery = order.get("delivery") or details.get("delivery") or "link"
    audio_data = order.get("audio_data") or details.get("audioData") or None

    return {
        "order_id": order.get("order_id"),
        "card_id": order.get("card_id"),
        "payment_id": order.get("payment_id"),
        "receipt": order.get("receipt"),
        "device_id": device_id,
        "sender_name": sender_name,
        "recipient_name": recipient_name,
        "message": message,
        "language": language,
        "email": email_val,
        "delivery": delivery,
        "amount": order.get("amount") or details.get("amount") or 100,
        "amount_paise": order.get("amount_paise") or 10000,
        "currency": order.get("currency") or "INR",
        "status": order.get("status") or "created",
        "share_url": order.get("share_url"),
        "audio_data": audio_data,
        "paid_at": order.get("paid_at"),
        "email_result": order.get("email_result"),
        "data": order,
    }

def _prepare_fallback_row(order: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal row dictionary for legacy/unmigrated Supabase schema."""
    details = order.get("details") or {}
    email_val = order.get("email") or details.get("email")
    if email_val:
        email_val = str(email_val).strip() or None
    else:
        email_val = None

    return {
        "order_id": order.get("order_id"),
        "card_id": order.get("card_id"),
        "device_id": order.get("device_id") or details.get("deviceId"),
        "email": email_val,
        "status": order.get("status") or "created",
        "data": order,
    }

def _row_to_order(row: Dict[str, Any]) -> Dict[str, Any]:
    """Merge row data so both top-level columns and nested json payload are unified."""
    order = dict(row.get("data") or {})
    for k, v in row.items():
        if k != "data" and v is not None:
            order[k] = v
    return order

async def get_all_orders() -> List[Dict[str, Any]]:
    """Retrieve all orders from Supabase or fallback JSON file."""
    if supabase_client:
        try:
            # Run in thread pool to prevent blocking asyncio event loop
            res = await asyncio.to_thread(
                lambda: supabase_client.table("orders")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            orders = [_row_to_order(row) for row in (res.data or [])]
            logger.debug("Supabase retrieved %d orders", len(orders))
            return orders
        except Exception as exc:
            logger.error("Supabase error in get_all_orders: %s. Falling back to local file.", exc)

    async with _lock:
        return _read_orders_sync()

async def get_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    """Find an order by order_id."""
    if supabase_client:
        try:
            res = await asyncio.to_thread(
                lambda: supabase_client.table("orders")
                .select("*")
                .eq("order_id", order_id)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0:
                return _row_to_order(res.data[0])
            return None
        except Exception as exc:
            logger.error("Supabase error in get_order_by_id: %s. Falling back to local file.", exc)

    async with _lock:
        orders = _read_orders_sync()
        for o in orders:
            if o.get("order_id") == order_id:
                return o
        return None

async def get_order_by_card_id(card_id: str) -> Optional[Dict[str, Any]]:
    """Find an order by unique card_id."""
    if supabase_client:
        try:
            res = await asyncio.to_thread(
                lambda: supabase_client.table("orders")
                .select("*")
                .eq("card_id", card_id)
                .limit(1)
                .execute()
            )
            if res.data and len(res.data) > 0:
                return _row_to_order(res.data[0])
            return None
        except Exception as exc:
            logger.error("Supabase error in get_order_by_card_id: %s. Falling back to local file.", exc)

    async with _lock:
        orders = _read_orders_sync()
        for o in orders:
            if o.get("card_id") == card_id:
                return o
        return None

async def save_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new order or update existing order matching order_id."""
    order_id = order.get("order_id")
    if supabase_client and order_id:
        try:
            full_row = _prepare_supabase_row(order)
            try:
                await asyncio.to_thread(
                    lambda: supabase_client.table("orders").upsert(full_row).execute()
                )
            except Exception as schema_exc:
                err_msg = str(schema_exc)
                if "Could not find the" in err_msg or "PGRST204" in err_msg:
                    logger.warning(
                        "Supabase table is missing detailed columns. Upserting with fallback schema. "
                        "Please run backend/schema.sql in Supabase SQL Editor. Error: %s",
                        schema_exc,
                    )
                    fallback_row = _prepare_fallback_row(order)
                    await asyncio.to_thread(
                        lambda: supabase_client.table("orders").upsert(fallback_row).execute()
                    )
                else:
                    raise schema_exc

            logger.info("Saved order to Supabase: %s (card_id=%s, status=%s)", order_id, order.get("card_id"), order.get("status"))
            return order
        except Exception as exc:
            logger.error("Supabase error in save_order: %s. Falling back to local file.", exc)

    async with _lock:
        orders = _read_orders_sync()
        existing_idx = next((i for i, o in enumerate(orders) if o.get("order_id") == order_id), None)
        if existing_idx is not None:
            orders[existing_idx].update(order)
        else:
            orders.append(order)
        _write_orders_sync(orders)
        return order

async def update_order(order_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update fields on an existing order."""
    if supabase_client:
        try:
            current = await get_order_by_id(order_id)
            if current:
                current.update(updates)
                return await save_order(current)
            return None
        except Exception as exc:
            logger.error("Supabase error in update_order: %s. Falling back to local file.", exc)

    async with _lock:
        orders = _read_orders_sync()
        for o in orders:
            if o.get("order_id") == order_id:
                o.update(updates)
                _write_orders_sync(orders)
                return o
        return None
