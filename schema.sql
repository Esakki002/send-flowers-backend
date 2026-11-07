-- ==============================================================================
-- SendFlowers: Supabase Database Schema for 'orders' table
-- ==============================================================================
-- Run this script in the Supabase SQL Editor:
-- https://supabase.com/dashboard/project/ajjjqkzhxgkkssiedbes/sql
-- ==============================================================================

-- 1. Create table if not exists (with order_id as Primary Key)
CREATE TABLE IF NOT EXISTS public.orders (
    order_id TEXT PRIMARY KEY,
    card_id TEXT UNIQUE,
    device_id TEXT,
    email TEXT,
    status TEXT DEFAULT 'created',
    data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Add structured columns to store order details cleanly
ALTER TABLE public.orders 
    ADD COLUMN IF NOT EXISTS payment_id TEXT,
    ADD COLUMN IF NOT EXISTS receipt TEXT,
    ADD COLUMN IF NOT EXISTS sender_name TEXT,
    ADD COLUMN IF NOT EXISTS recipient_name TEXT,
    ADD COLUMN IF NOT EXISTS message TEXT,
    ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en',
    ADD COLUMN IF NOT EXISTS delivery TEXT DEFAULT 'link',
    ADD COLUMN IF NOT EXISTS amount NUMERIC DEFAULT 100,
    ADD COLUMN IF NOT EXISTS amount_paise BIGINT DEFAULT 10000,
    ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'INR',
    ADD COLUMN IF NOT EXISTS share_url TEXT,
    ADD COLUMN IF NOT EXISTS audio_data TEXT,
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_result JSONB;

-- 3. Create indices for fast lookup queries
CREATE INDEX IF NOT EXISTS idx_orders_card_id ON public.orders (card_id);
CREATE INDEX IF NOT EXISTS idx_orders_device_id ON public.orders (device_id);
CREATE INDEX IF NOT EXISTS idx_orders_email ON public.orders (email);
CREATE INDEX IF NOT EXISTS idx_orders_status ON public.orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON public.orders (created_at DESC);

-- 4. Backfill any existing records from their 'data' JSONB column
UPDATE public.orders
SET
    payment_id = COALESCE(payment_id, data->>'payment_id'),
    receipt = COALESCE(receipt, data->>'receipt'),
    sender_name = COALESCE(sender_name, data->>'sender_name', data->'details'->>'senderName'),
    recipient_name = COALESCE(recipient_name, data->>'recipient_name', data->'details'->>'recipientName'),
    message = COALESCE(message, data->>'message', data->'details'->>'message'),
    language = COALESCE(language, data->>'language', data->'details'->>'language', 'en'),
    delivery = COALESCE(delivery, data->>'delivery', data->'details'->>'delivery', 'link'),
    amount = COALESCE(amount, (data->>'amount')::NUMERIC, (data->'details'->>'amount')::NUMERIC, 100),
    amount_paise = COALESCE(amount_paise, (data->>'amount_paise')::BIGINT, 10000),
    currency = COALESCE(currency, data->>'currency', 'INR'),
    share_url = COALESCE(share_url, data->>'share_url'),
    audio_data = COALESCE(audio_data, data->>'audio_data', data->'details'->>'audioData'),
    paid_at = COALESCE(paid_at, (data->>'paid_at')::TIMESTAMPTZ),
    email = COALESCE(NULLIF(email, ''), NULLIF(data->>'email', ''), NULLIF(data->'details'->>'email', '')),
    email_result = COALESCE(email_result, data->'email_result')
WHERE data IS NOT NULL;

