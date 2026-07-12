import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

INVITE_EMAIL_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; margin: 0; padding: 40px 20px; }}
    .container {{ max-width: 560px; margin: 0 auto; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; }}
    .header {{ background: #2563eb; padding: 32px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; font-weight: 700; }}
    .header p {{ color: #bfdbfe; margin: 8px 0 0; font-size: 13px; }}
    .body {{ padding: 32px; }}
    .body p {{ color: #475569; font-size: 14px; line-height: 1.6; margin: 0 0 16px; }}
    .permissions {{ background: #f1f5f9; border-radius: 8px; padding: 16px; margin: 20px 0; }}
    .permissions h3 {{ margin: 0 0 12px; font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}
    .perm-row {{ display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #e2e8f0; }}
    .perm-row:last-child {{ border: none; }}
    .perm-service {{ font-size: 13px; font-weight: 600; color: #334155; }}
    .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 20px; }}
    .badge-write {{ background: #dcfce7; color: #15803d; }}
    .badge-read {{ background: #dbeafe; color: #1d4ed8; }}
    .badge-none {{ background: #f1f5f9; color: #94a3b8; }}
    .cta {{ text-align: center; margin: 28px 0 8px; }}
    .btn {{ display: inline-block; background: #2563eb; color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 700; font-size: 15px; }}
    .expiry {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 20px; }}
    .footer {{ padding: 20px 32px; border-top: 1px solid #f1f5f9; text-align: center; }}
    .footer p {{ font-size: 12px; color: #94a3b8; margin: 0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>DCollect</h1>
      <p>Workspace Collaboration Invitation</p>
    </div>
    <div class="body">
      <p>Hi there!</p>
      <p><strong>{inviter_name}</strong> has invited you to collaborate on the <strong>{workspace_name}</strong> workspace in DCollect.</p>
      <div class="permissions">
        <h3>Your Access Permissions</h3>
        {permissions_html}
      </div>
      <div class="cta">
        <a href="{accept_url}" class="btn">Accept Invitation</a>
      </div>
      <p class="expiry">This invitation expires in <strong>3 days</strong>. After expiry, ask the workspace owner to resend the invitation.</p>
    </div>
    <div class="footer">
      <p>If you didn't expect this invitation, you can safely ignore this email.</p>
      <p style="margin-top:8px; color:#cbd5e1;">DCollect &bull; Workspace Management Platform</p>
    </div>
  </div>
</body>
</html>
"""

SERVICE_LABELS = {
    "forms": "Forms",
    "qrcodes": "QR Codes",
    "cards": "Business Cards",
    "tasks": "Tasks Manager",
    "documents": "Documentation",
    "assets": "Asset Management",
}

def build_permissions_html(service_permissions: dict) -> str:
    rows = []
    for key, label in SERVICE_LABELS.items():
        perm = service_permissions.get(key, "none")
        badge_class = f"badge-{perm}"
        badge_text = perm.capitalize()
        rows.append(
            f'<div class="perm-row">'
            f'<span class="perm-service">{label}</span>'
            f'<span class="badge {badge_class}">{badge_text}</span>'
            f'</div>'
        )
    return "\n".join(rows)

async def send_invitation_email(
    to_email: str,
    inviter_name: str,
    workspace_name: str,
    accept_url: str,
    service_permissions: dict,
) -> bool:
    """Send invitation email. Returns True on success, False on failure."""
    if not settings.SMTP_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.info(f"[EMAIL DISABLED] Invitation link for {to_email}: {accept_url}")
        return False

    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        permissions_html = build_permissions_html(service_permissions)
        html_body = INVITE_EMAIL_HTML.format(
            inviter_name=inviter_name,
            workspace_name=workspace_name,
            accept_url=accept_url,
            permissions_html=permissions_html,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"You're invited to {workspace_name} on DCollect"
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email

        plain_text = (
            f"Hi! {inviter_name} invited you to join '{workspace_name}' on DCollect.\n\n"
            f"Accept invitation: {accept_url}\n\n"
            f"This link expires in 3 days."
        )
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"Invitation email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send invitation email to {to_email}: {e}")
        logger.info(f"[FALLBACK] Invitation link for {to_email}: {accept_url}")
        return False
