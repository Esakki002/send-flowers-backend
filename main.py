import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import razorpay

from config import (
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    FRONTEND_URL,
    ROSE_PRICE_INR,
    HOST,
    PORT,
    SMTP_USER,
    SMTP_PASSWORD,
)
import database
from email_service import send_rose_email
from rate_limiter import RateLimitAndSecurityMiddleware

# Configure structured logging for the entire backend application
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sendflowers.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown logging."""
    logger.info("==========================================================")
    logger.info("🌸 SendFlowers 3D Rose Platform Backend Starting Up")
    logger.info("Host Binding: %s:%d | Frontend Origin: %s", HOST, PORT, FRONTEND_URL)
    logger.info("Standard Rose Price: ₹%d INR", ROSE_PRICE_INR)
    logger.info(
        "Razorpay Gateway: %s",
        "MOCK MODE (using test fallback)" if is_mock_key() else f"CONFIGURED ({RAZORPAY_KEY_ID[:10]}...)",
    )
    logger.info(
        "SMTP Email Service: %s",
        "ENABLED (Live SMTP dispatch)" if (SMTP_USER and SMTP_PASSWORD) else "SIMULATED (Logs & console only)",
    )
    logger.info("Database File Path: %s", database.ORDERS_FILE)
    logger.info("==========================================================")
    yield
    logger.info("🌸 SendFlowers Backend Server Shutting Down Gracefully")

app = FastAPI(
    title="SendFlowers Backend",
    description="Backend for SendFlowers 3D Rose Gift Platform with Razorpay, Rate Limiting & Security",
    version="1.0.0",
    lifespan=lifespan,
)

# 1. Security headers & Rate limiting middleware
app.add_middleware(RateLimitAndSecurityMiddleware)

# 2. CORS middleware for frontend Vite app
configured_origins = [orig.strip().rstrip("/") for orig in FRONTEND_URL.split(",") if orig.strip()]
allowed_origins = list(set([
    *configured_origins,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Request Models with validation & size limits
class CreateOrderRequest(BaseModel):
    senderName: str = Field(..., min_length=1, max_length=100)
    recipientName: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=500)
    language: str = Field("en", pattern="^(en|ta)$")
    email: Optional[str] = Field("", max_length=255)
    delivery: str = Field("link", pattern="^(email|qr|link)$")
    amount: Optional[int] = Field(None, ge=1, le=100000)
    deviceId: Optional[str] = Field(None, max_length=128)
    audioData: Optional[str] = Field(None, max_length=5_000_000)

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = Field(..., max_length=128)
    razorpay_payment_id: str = Field(..., max_length=128)
    razorpay_signature: str = Field(..., max_length=256)
    senderName: str = Field(..., min_length=1, max_length=100)
    recipientName: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=500)
    language: str = Field("en", pattern="^(en|ta)$")
    email: Optional[str] = Field("", max_length=255)
    delivery: str = Field("link", pattern="^(email|qr|link)$")
    cardId: Optional[str] = Field(None, max_length=64)
    deviceId: Optional[str] = Field(None, max_length=128)
    audioData: Optional[str] = Field(None, max_length=5_000_000)

def get_razorpay_client() -> razorpay.Client:
    """Initialize and return a Razorpay API client."""
    logger.debug(
        "Instantiating Razorpay client with key_id: %s",
        (RAZORPAY_KEY_ID[:8] + "...") if RAZORPAY_KEY_ID else "None",
    )
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def is_mock_key() -> bool:
    """Check if Razorpay API keys are placeholders or unconfigured."""
    is_mock = (
        not RAZORPAY_KEY_ID
        or "your_key" in RAZORPAY_KEY_ID
        or not RAZORPAY_KEY_SECRET
        or "your_key" in RAZORPAY_KEY_SECRET
    )
    logger.debug("Evaluated is_mock_key: %s", is_mock)
    return is_mock

@app.get("/api/health")
async def health_check():
    """Health check endpoint to verify server status and gateway integration."""
    razorpay_ready = not is_mock_key()
    logger.info("Health check endpoint queried. Status: healthy, Razorpay ready: %s", razorpay_ready)
    return {
        "status": "healthy",
        "service": "sendflowers-backend",
        "razorpay_configured": razorpay_ready,
    }

@app.get("/api/config")
async def get_config():
    """Return public configuration for client initialization."""
    mock_mode = is_mock_key()
    key_to_return = RAZORPAY_KEY_ID if not mock_mode else "rzp_test_mock_mode"
    logger.info("Public configuration requested. Price: ₹%d, isMock: %s", ROSE_PRICE_INR, mock_mode)
    return {
        "razorpayKeyId": key_to_return,
        "priceInr": ROSE_PRICE_INR,
        "isMockMode": mock_mode,
    }

@app.post("/api/payment/create-order")
async def create_payment_order(req: CreateOrderRequest):
    """Create a new payment order via Razorpay or generate a mock test order."""
    price_in_rupees = req.amount or ROSE_PRICE_INR
    amount_in_paise = price_in_rupees * 100
    currency = "INR"

    receipt_id = f"rcpt_{secrets.token_hex(6)}"

    logger.info(
        "Processing create-order: sender='%s', recipient='%s', delivery='%s', price=₹%d (%d paise)",
        req.senderName,
        req.recipientName,
        req.delivery,
        price_in_rupees,
        amount_in_paise,
    )

    # If mock keys are in use, generate a mock order to allow end-to-end testing without blocking
    if is_mock_key():
        logger.warning(
            "Razorpay API Keys are not set or using placeholder! Generating mock order for end-to-end testing."
        )
        mock_order_id = f"order_mock_{secrets.token_hex(8)}"
        order_record = {
            "order_id": mock_order_id,
            "receipt": receipt_id,
            "amount": price_in_rupees,
            "amount_paise": amount_in_paise,
            "currency": currency,
            "status": "created",
            "is_mock": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "details": req.model_dump(),
        }
        await database.save_order(order_record)
        logger.info(
            "Mock order created successfully: %s (amount: ₹%d, receipt: %s)",
            mock_order_id,
            price_in_rupees,
            receipt_id,
        )
        return {
            "orderId": mock_order_id,
            "amount": amount_in_paise,
            "amountInRupees": price_in_rupees,
            "currency": currency,
            "keyId": "rzp_test_mock_mode",
            "isMock": True,
            "message": "Mock order created. To use real Razorpay test checkout, update RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in backend/.env",
        }

    try:
        logger.debug("Contacting Razorpay API to create order with amount=%d paise", amount_in_paise)
        client = get_razorpay_client()
        order_data = {
            "amount": amount_in_paise,
            "currency": currency,
            "receipt": receipt_id,
            "notes": {
                "senderName": req.senderName,
                "recipientName": req.recipientName,
                "delivery": req.delivery,
            },
        }
        order = client.order.create(data=order_data)
        logger.info(
            "Razorpay order created successfully: order_id='%s', amount=%d paise (₹%d), receipt='%s'",
            order["id"],
            amount_in_paise,
            price_in_rupees,
            receipt_id,
        )

        order_record = {
            "order_id": order["id"],
            "receipt": receipt_id,
            "amount": price_in_rupees,
            "amount_paise": amount_in_paise,
            "currency": currency,
            "status": "created",
            "is_mock": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "details": req.model_dump(),
        }
        await database.save_order(order_record)

        return {
            "orderId": order["id"],
            "amount": order["amount"],
            "amountInRupees": price_in_rupees,
            "currency": order["currency"],
            "keyId": RAZORPAY_KEY_ID,
            "isMock": False,
        }
    except Exception as e:
        logger.error(
            "Failed to create Razorpay order for sender '%s' to '%s': %s",
            req.senderName,
            req.recipientName,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create Razorpay order: {str(e)}",
        )

@app.post("/api/payment/verify-payment")
async def verify_payment(req: VerifyPaymentRequest):
    """Verify Razorpay payment signature and dispatch the rose gift card."""
    order_id = req.razorpay_order_id
    payment_id = req.razorpay_payment_id
    signature = req.razorpay_signature

    logger.info(
        "Verifying payment for order_id='%s', payment_id='%s' (sender='%s', recipient='%s')",
        order_id,
        payment_id,
        req.senderName,
        req.recipientName,
    )

    # Verify signature
    is_valid = False
    if order_id.startswith("order_mock_") or is_mock_key():
        # In mock testing mode, accept mock signature
        logger.info("Mock signature accepted for testing mode: %s / %s", order_id, payment_id)
        is_valid = True
    else:
        try:
            client = get_razorpay_client()
            client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": signature,
                }
            )
            is_valid = True
            logger.info("Razorpay SDK signature check passed for order_id: %s", order_id)
        except razorpay.errors.SignatureVerificationError:
            logger.warning("SDK signature check failed for order_id: %s. Attempting fallback HMAC SHA256", order_id)
            # Check manual HMAC SHA256 fallback
            generated_signature = hmac.new(
                RAZORPAY_KEY_SECRET.encode("utf-8"),
                f"{order_id}|{payment_id}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            is_valid = hmac.compare_digest(generated_signature, signature)
            if is_valid:
                logger.info("Fallback HMAC signature verification passed for order_id: %s", order_id)
            else:
                logger.error("Fallback HMAC signature mismatch for order_id: %s", order_id)
        except Exception as e:
            logger.error("Unexpected error during signature verification for order_id '%s': %s", order_id, e, exc_info=True)
            is_valid = False

    if not is_valid:
        logger.warning(
            "Payment verification REJECTED for order_id='%s', payment_id='%s'. Invalid signature.",
            order_id,
            payment_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment signature. Payment verification failed.",
        )

    # Generate a unique card ID
    card_id = req.cardId or secrets.token_urlsafe(8)
    import urllib.parse
    import json
    card_param = urllib.parse.quote(
        json.dumps({
            "senderName": req.senderName,
            "recipientName": req.recipientName,
            "message": req.message,
            "language": req.language,
        })
    )
    share_url = f"{FRONTEND_URL}/c/{card_id}?card={card_param}"
    logger.debug("Generated rose card_id='%s' with share_url='%s'", card_id, share_url)

    # Send rose email if email is provided
    email_result = None
    if req.email and (req.delivery == "email" or "@" in req.email):
        try:
            logger.info("Dispatching rose email to recipient: %s", req.email)
            email_result = await send_rose_email(
                to_email=req.email,
                sender_name=req.senderName,
                recipient_name=req.recipientName,
                message=req.message,
                share_url=share_url,
                language=req.language,
            )
            logger.info("Email delivery result for %s: %s", req.email, email_result.get("status"))
        except Exception as err:
            logger.error("Failed to send rose email to %s: %s", req.email, err, exc_info=True)
            email_result = {"success": False, "status": "error", "error": str(err)}

    # Save finalized order to local JSON database
    existing_order = await database.get_order_by_id(order_id)
    order_amount = (
        existing_order.get("amount")
        if existing_order and existing_order.get("amount") is not None
        else ROSE_PRICE_INR
    )
    amount_paise = (
        existing_order.get("amount_paise")
        if existing_order and existing_order.get("amount_paise") is not None
        else order_amount * 100
    )
    final_order = {
        "order_id": order_id,
        "payment_id": payment_id,
        "amount": order_amount,
        "amount_paise": amount_paise,
        "currency": "INR",
        "status": "PAID",
        "card_id": card_id,
        "device_id": req.deviceId or "",
        "sender_name": req.senderName,
        "recipient_name": req.recipientName,
        "message": req.message,
        "language": req.language,
        "email": req.email,
        "delivery": req.delivery,
        "audio_data": req.audioData or "",
        "share_url": share_url,
        "paid_at": datetime.now(timezone.utc).isoformat(),
        "email_result": email_result,
    }
    await database.save_order(final_order)
    logger.info("Successfully completed order %s. Card ID: %s, Paid Amount: ₹%d", order_id, card_id, order_amount)

    return {
        "success": True,
        "cardId": card_id,
        "shareUrl": share_url,
        "delivery": req.delivery,
        "emailResult": email_result,
        "message": "Payment verified and rose card created successfully!",
    }

@app.get("/api/orders")
async def get_orders(device_id: Optional[str] = None, email: Optional[str] = None):
    """Retrieve paid orders for the specific user/device or matching email."""
    logger.info("Orders query received: device_id='%s', email='%s'", device_id, email)
    all_orders = await database.get_all_orders()
    paid_orders = [o for o in all_orders if o.get("status") == "PAID"]

    if device_id:
        paid_orders = [o for o in paid_orders if o.get("device_id") == device_id]
        logger.debug("Filtered %d orders matching device_id='%s'", len(paid_orders), device_id)
    elif email:
        email_clean = email.strip().lower()
        paid_orders = [o for o in paid_orders if (o.get("email") or "").strip().lower() == email_clean]
        logger.debug("Filtered %d orders matching email='%s'", len(paid_orders), email_clean)
    else:
        logger.debug("Neither device_id nor email was supplied. Returning empty orders list for privacy.")
        return []

    paid_orders.sort(key=lambda x: x.get("paid_at") or x.get("created_at") or "", reverse=True)
    logger.info("Returning %d paid orders for query (device_id='%s', email='%s')", len(paid_orders), device_id, email)
    return paid_orders

@app.get("/api/card/{card_id}")
async def get_card(card_id: str):
    """Retrieve card details by card_id from local JSON store."""
    logger.info("Lookup requested for rose card_id='%s'", card_id)
    order = await database.get_order_by_card_id(card_id)
    if not order:
        logger.warning("Rose card not found: card_id='%s'", card_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rose card not found",
        )

    details = order.get("details") or {}
    logger.debug(
        "Successfully retrieved rose card '%s' (recipient='%s', sender='%s')",
        card_id,
        order.get("recipient_name") or details.get("recipientName"),
        order.get("sender_name") or details.get("senderName"),
    )
    return {
        "senderName": order.get("sender_name") or details.get("senderName", ""),
        "recipientName": order.get("recipient_name") or details.get("recipientName", ""),
        "message": order.get("message") or details.get("message", ""),
        "language": order.get("language") or details.get("language", "en"),
        "delivery": order.get("delivery") or details.get("delivery", "link"),
        "audioData": order.get("audio_data") or details.get("audioData") or order.get("audioData", ""),
        "created_at": order.get("paid_at") or order.get("created_at"),
    }
