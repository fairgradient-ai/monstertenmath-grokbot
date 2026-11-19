"""Sending creator outreach by email (SMTP, standard library).

The address and an app password come from the secret card (SMTP_USER, SMTP_PASSWORD). For Gmail or Google
Workspace that's an App Password (SETUP.md, section 14), never the account password.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from ..errors import ChannelError


class SmtpEmail:
    def __init__(self, *, host: str, port: int, user: str, password: str, from_name: str, from_email: str):
        if not (user and password):
            raise ChannelError("no email login: add SMTP_USER and SMTP_PASSWORD on the secret card", "token")
        if not from_email:
            raise ChannelError("outreach.from_email isn't set in config.toml", "bad_request")
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender = formataddr((from_name, from_email)) if from_name else from_email
        self.from_email = from_email

    def send(self, to: str, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg["Reply-To"] = self.from_email
        msg_id = make_msgid(domain=self.from_email.split("@")[-1])
        msg["Message-ID"] = msg_id
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            raise ChannelError("the email login was refused (check the app password)", "token") from e
        except (smtplib.SMTPException, OSError) as e:
            raise ChannelError(f"email not sent: {e}", "network") from e
        return msg_id
