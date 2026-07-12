import logging

logger = logging.getLogger(__name__)

def send_otp_email(email_to: str, otp: str):
    """
    Mock function to send OTP email.
    In a real app, this would use SMTP or an email API like SendGrid.
    """
    logger.info(f"--- EMAIL MOCK ---")
    logger.info(f"To: {email_to}")
    logger.info(f"Subject: Your Login OTP")
    logger.info(f"Body: Your OTP is {otp}")
    logger.info(f"------------------")

def send_invite_email(email_to: str, invite_link: str, inviter_name: str, form_name: str):
    """
    Mock function to send an invite email.
    """
    logger.info(f"--- EMAIL MOCK ---")
    logger.info(f"To: {email_to}")
    logger.info(f"Subject: You've been invited to {form_name}")
    logger.info(f"Body: {inviter_name} has invited you to collaborate. Click here: {invite_link}")
    logger.info(f"------------------")
