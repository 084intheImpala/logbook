"""Email sending helpers using Gmail SMTP."""
import aiosmtplib
from email.message import EmailMessage
from backend.config import settings


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on failure."""
    msg = EmailMessage()
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        start_tls=True,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
    )


async def send_welcome_email(
    to: str,
    username: str,
    temp_password: str,
    magic_link: str | None = None,
) -> None:
    """Sent when an admin creates a new account."""
    if magic_link:
        link_section = f"""\
Click the link below to log in and set your own password (valid for 72 hours):

  {magic_link}

Or log in manually with your temporary credentials:"""
    else:
        link_section = "Log in with your temporary credentials at:"

    body = f"""\
Hello,

An account has been created for you on the CTN Thin Film Logbook.

  Username:           {username}
  Temporary password: {temp_password}

{link_section}
  {settings.BASE_URL}/login

You will be asked to choose a new password on your first login.
The magic link above can only be used once — after that, use your username
and the password you set.

If you didn't expect this email, you can ignore it.

— CTN Logbook
"""
    await send_email(to, "Welcome to CTN Logbook — your new account", body)


async def send_password_reset_email(
    to: str,
    username: str,
    magic_link: str,
) -> None:
    """Sent when a user requests a password reset."""
    body = f"""\
Hello,

A password reset was requested for the CTN Thin Film Logbook account
associated with this email address.

  Username: {username}

Click the link below to set a new password (valid for 72 hours):

  {magic_link}

This link can only be used once. If you didn't request a reset, you can
safely ignore this email — your password has not been changed.

— CTN Logbook
"""
    await send_email(to, "CTN Logbook — password reset request", body)
