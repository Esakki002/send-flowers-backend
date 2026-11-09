import logging
from email.message import EmailMessage
from typing import Dict, Any
import httpx
import aiosmtplib
from config import (
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_USE_TLS,
)

logger = logging.getLogger("sendflowers.email")

def generate_rose_email_html(
    sender_name: str,
    recipient_name: str,
    message: str,
    share_url: str,
    language: str = "en",
) -> str:
    logger.debug(
        "Rendering rose email HTML template (recipient='%s', sender='%s', language='%s')",
        recipient_name,
        sender_name,
        language,
    )
    lang_greeting = "வணக்கம்" if language == "ta" else "Hello"
    lang_sent = f"{sender_name} உங்களுக்கு ஒரு ரோஜாவை அனுப்பியுள்ளார் 🌹" if language == "ta" else f"{sender_name} sent you a digital rose 🌹"
    lang_btn = "உங்கள் ரோஜாவைப் பார்க்கவும்" if language == "ta" else "View Your 3D Rose"
    lang_footer = "இந்த ரோஜா ஒருபோதும் வாடாது." if language == "ta" else "A digital rose that never wilts."

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{lang_sent}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #1a0f16; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f5eff2;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #1a0f16; padding: 32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 540px; background: linear-gradient(145deg, #2a1522 0%, #170d14 100%); border: 1px solid rgba(198, 91, 117, 0.3); border-radius: 20px; overflow: hidden; box-shadow: 0 20px 40px rgba(0,0,0,0.5);">
          <!-- Top Accent Bar -->
          <tr>
            <td style="background: linear-gradient(90deg, #991b1b, #ec4899, #f43f5e); height: 6px;"></td>
          </tr>
          <!-- Body Content -->
          <tr>
            <td style="padding: 36px 32px; text-align: center;">
              <div style="font-size: 40px; margin-bottom: 16px;">🌹</div>
              <h1 style="color: #ffffff; font-size: 24px; font-weight: 700; margin: 0 0 8px 0; font-family: Georgia, serif;">
                {lang_greeting} {recipient_name},
              </h1>
              <p style="color: #e5b3c3; font-size: 16px; margin: 0 0 24px 0;">
                {lang_sent}
              </p>

              <!-- Personal Message Card -->
              <div style="background-color: rgba(255, 255, 255, 0.05); border-left: 3px solid #ec4899; border-radius: 10px; padding: 20px; text-align: left; margin-bottom: 28px;">
                <p style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #c08497; margin: 0 0 8px 0; font-weight: 600;">
                  Personal Message
                </p>
                <p style="color: #fce7f3; font-size: 15px; line-height: 1.6; margin: 0; font-style: italic; white-space: pre-wrap;">
                  "{message}"
                </p>
              </div>

              <!-- Button -->
              <div style="margin: 28px 0;">
                <a href="{share_url}" target="_blank" style="background: linear-gradient(135deg, #be123c, #9d174d); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 30px; font-size: 16px; font-weight: 600; display: inline-block; box-shadow: 0 6px 16px rgba(190, 18, 60, 0.4);">
                  {lang_btn} →
                </a>
              </div>

              <p style="font-size: 12px; color: #a17b8b; margin-top: 24px; word-break: break-all;">
                Or open this link: <br>
                <a href="{share_url}" style="color: #f472b6; text-decoration: underline;">{share_url}</a>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 16px; background-color: rgba(0, 0, 0, 0.25); text-align: center; border-top: 1px solid rgba(255, 255, 255, 0.05);">
              <p style="margin: 0; font-size: 12px; color: #8a6575;">
                SendFlowers • {lang_footer}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

async def send_rose_email(
    to_email: str,
    sender_name: str,
    recipient_name: str,
    message: str,
    share_url: str,
    language: str = "en",
) -> Dict[str, Any]:
    logger.info(
        "Initiating rose email send request (to='%s', sender='%s', recipient='%s', language='%s')",
        to_email,
        sender_name,
        recipient_name,
        language,
    )
    if not to_email or not to_email.strip():
        logger.warning("Email sending skipped: No recipient email provided")
        return {"success": False, "status": "skipped", "message": "No recipient email provided"}

    to_email = to_email.strip()
    subject = f"{sender_name} sent you a rose 🌹"

    html_content = generate_rose_email_html(
        sender_name=sender_name,
        recipient_name=recipient_name,
        message=message,
        share_url=share_url,
        language=language,
    )
    text_content = (
        f"Hello {recipient_name},\n\n"
        f"{sender_name} sent you a digital rose!\n\n"
        f"Personal message:\n\"{message}\"\n\n"
        f"View your 3D rose here:\n{share_url}\n\n"
        f"---\nSendFlowers"
    )

    # 1. Preferred: Send via Resend API
    if RESEND_API_KEY:
        logger.info("Attempting to send rose email to '%s' via Resend API", to_email)
        headers = {
            "Authorization": f"Bearer {RESEND_API_KEY.strip()}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    "https://api.resend.com/emails",
                    headers=headers,
                    json=payload,
                )

            if 200 <= res.status_code < 300:
                data = res.json()
                email_id = data.get("id")
                logger.info(
                    "Rose email delivered successfully to '%s' via Resend (email_id='%s')",
                    to_email,
                    email_id,
                )
                return {
                    "success": True,
                    "status": "sent",
                    "message": "Email sent successfully via Resend",
                    "to": to_email,
                    "id": email_id,
                }
            else:
                err_detail = res.text
                try:
                    err_json = res.json()
                    err_detail = err_json.get("message", res.text)
                except Exception:
                    pass
                logger.error(
                    "Resend API error (%d) sending email to '%s': %s",
                    res.status_code,
                    to_email,
                    err_detail,
                )
                if not (SMTP_USER and SMTP_PASSWORD):
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"Resend API error ({res.status_code}): {err_detail}",
                        "to": to_email,
                    }
                logger.info("Falling back to SMTP dispatch after Resend error...")
        except Exception as e:
            logger.error(
                "Exception while sending email to '%s' via Resend: %s",
                to_email,
                e,
                exc_info=True,
            )
            if not (SMTP_USER and SMTP_PASSWORD):
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Failed to send email via Resend: {str(e)}",
                    "to": to_email,
                }
            logger.info("Falling back to SMTP dispatch after Resend exception...")

    # 2. Fallback: Send via SMTP if configured
    if SMTP_USER and SMTP_PASSWORD:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email
        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype="html")

        logger.debug(
            "Connecting to SMTP server at %s:%d (from='%s', TLS=%s)",
            SMTP_HOST,
            SMTP_PORT,
            SMTP_FROM_EMAIL,
            SMTP_USE_TLS,
        )
        try:
            if SMTP_PORT == 465:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    username=SMTP_USER,
                    password=SMTP_PASSWORD,
                    use_tls=True,
                    timeout=15,
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=SMTP_HOST,
                    port=SMTP_PORT,
                    username=SMTP_USER,
                    password=SMTP_PASSWORD,
                    start_tls=SMTP_USE_TLS,
                    timeout=15,
                )
            logger.info("Rose email delivered successfully to '%s' via SMTP (%s:%d)", to_email, SMTP_HOST, SMTP_PORT)
            return {"success": True, "status": "sent", "message": "Email sent successfully via SMTP", "to": to_email}
        except Exception as e:
            logger.error("Failed to send rose email to '%s' via SMTP: %s", to_email, e, exc_info=True)
            return {
                "success": False,
                "status": "error",
                "message": f"Failed to send email: {str(e)}",
                "to": to_email,
            }

    # 3. Neither Resend nor SMTP configured -> Simulation
    logger.info(
        "[SIMULATED EMAIL] No email provider configured in backend/.env. Simulated delivery to: '%s' | Subject: '%s' | Card: %s",
        to_email,
        subject,
        share_url,
    )
    print("\n" + "=" * 60)
    print(f"📧 [SIMULATED EMAIL - NO EMAIL PROVIDER CONFIGURED]")
    print(f"To: {to_email}")
    print(f"Subject: {subject}")
    print(f"From: {sender_name}")
    print(f"Card URL: {share_url}")
    print(f"Message: {message}")
    print("To send real emails, set RESEND_API_KEY in backend/.env")
    print("=" * 60 + "\n")
    return {
        "success": True,
        "status": "simulated",
        "message": "Email simulated (configure RESEND_API_KEY in backend/.env to send real emails)",
        "to": to_email,
    }

