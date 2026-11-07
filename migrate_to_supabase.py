#!/usr/bin/env python3
"""
Script to migrate existing orders from backend/data/orders.json to Supabase.
Usage: python migrate_to_supabase.py
"""
import json
import logging
from config import ORDERS_FILE, SUPABASE_URL, SUPABASE_KEY
from database import _prepare_supabase_row, _prepare_fallback_row

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def migrate():
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_KEY must be set in your backend/.env before migrating.")
        return

    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    if not ORDERS_FILE.exists():
        logger.warning("No orders.json file found to migrate.")
        return

    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        try:
            orders = json.load(f)
        except Exception as e:
            logger.error("Failed to parse %s: %s", ORDERS_FILE, e)
            return

    logger.info("Found %d orders in %s to migrate...", len(orders), ORDERS_FILE)
    count = 0
    for order in orders:
        order_id = order.get("order_id")
        if not order_id:
            continue
        row = _prepare_supabase_row(order)
        try:
            try:
                supabase.table("orders").upsert(row).execute()
            except Exception as schema_err:
                err_msg = str(schema_err)
                if "Could not find the" in err_msg or "PGRST204" in err_msg:
                    row_fb = _prepare_fallback_row(order)
                    supabase.table("orders").upsert(row_fb).execute()
                else:
                    raise schema_err
            count += 1
            logger.info("Migrated order: %s (card_id=%s, email=%s)", order_id, order.get("card_id"), row.get("email"))
        except Exception as e:
            logger.error("Failed to migrate order %s: %s", order_id, e)

    logger.info("Migration complete! %d / %d orders uploaded to Supabase.", count, len(orders))

if __name__ == "__main__":
    migrate()
