"""Sending email. ADR-0026, open question **K1**.

The only outbound channel in this system that reaches a *person* rather than a
program, and it exists for one reason: the merchant console signs people in with
a one-time link, so **if this does not work, nobody can log in at all.**

## Plain SMTP, deliberately

Not a provider SDK. [blueprint-v2 §5](../../../../docs/business/blueprint-v2.md)
sells a sovereign tier that runs entirely inside a customer's own perimeter, and
such a deployment can point SMTP at its own mail server. It cannot point an API
key at a service in another country. A hosted provider may be added *alongside*
this later; it must never replace it. **K1 is still open** — Gmail with an app
password is a development answer, not a production one.

## An unconfigured mailer is not an error

``smtp_host`` is empty on every developer machine and in every test run, and the
correct behaviour there is to **skip the send and say so loudly**, not to raise.
A test suite that needed a mail server would be a test suite nobody runs, and a
`make check` that failed without one would train people to ignore it.

But *silently* skipping is worse than either. :class:`SendResult` distinguishes
sent, skipped and failed, and callers are expected to log which — the same rule
the eval harness learned the expensive way about unreachable providers (**E6**):
a thing that did not happen must never look identical to a thing that succeeded.

## What must never appear in a log line here

The message body. A sign-in link **is** a credential for the length of its life,
so logging the rendered email would put a working session in the log file — the
one place it is most likely to be read by someone who should not have it. This
module logs the recipient, the subject and the outcome, and nothing else.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from neura_core.config import Settings, get_settings
from neura_core.logging import get_logger

log = get_logger(__name__)

#: Seconds to wait on the SMTP conversation. Short on purpose: this runs on the
#: request path of a sign-in form, and a merchant staring at a spinner for a
#: minute concludes the product is broken. A slow mail server should surface as
#: a failure we can see, not as a hung request.
TIMEOUT_S = 15


@dataclass(frozen=True, slots=True)
class SendResult:
    """What happened. Three outcomes, never two.

    ``skipped`` is not a quiet success — it means no mail server is configured
    and nobody received anything. A caller that treats it as ``sent`` will show
    a merchant "check your inbox" for a message that was never written.
    """

    sent: bool
    skipped: bool = False
    error: str = ""

    @property
    def delivered_to_a_server(self) -> bool:
        """True only when a real SMTP server accepted the message.

        Accepting is not delivering — the mail can still bounce or land in spam,
        which for sign-in mail is the failure mode that actually bites. Nothing
        here can see that, and this property does not pretend to.
        """
        return self.sent


class Mailer:
    """Sends mail over SMTP, or explains why it did not."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.smtp_host)

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        """Send one plain-text message.

        Plain text and not HTML, for now and on purpose: a text-only sign-in mail
        is smaller, renders identically everywhere, and is markedly less likely
        to be filtered as spam than a styled one — which matters more here than
        anywhere else, because a login link in a spam folder reads to a merchant
        as a product that does not work.
        """
        if not self.configured:
            # Skipped, and audible. See the module docstring: silence here is
            # how "nobody could log in" becomes a mystery instead of a message.
            log.warning("email_skipped_no_smtp_host", to=to, subject=subject)
            return SendResult(sent=False, skipped=True, error="no SMTP host configured")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_header()
        message["To"] = to
        message.set_content(body)

        settings = self._settings
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_S) as smtp:
                # STARTTLS on the standard submission port. Unencrypted SMTP
                # would put a working sign-in link on the wire in clear text.
                smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
        except Exception as exc:
            # Deliberately broad. smtplib raises a dozen unrelated exception
            # types plus socket and TLS errors, and the caller's decision is
            # identical for all of them: tell the person it did not send. The
            # type is kept in the log so the cause is still diagnosable.
            log.error("email_send_failed", to=to, subject=subject, error=type(exc).__name__)
            return SendResult(sent=False, error=f"{type(exc).__name__}: {exc}")

        log.info("email_sent", to=to, subject=subject)
        return SendResult(sent=True)

    def _from_header(self) -> str:
        """The configured sender, normalised.

        Accepts either ``Name <addr@host>`` or a bare address, so a deployment
        that sets only an address still produces a well-formed header rather than
        mail some providers reject.
        """
        name, address = parseaddr(self._settings.smtp_from)
        if not address:
            # Nothing parseable. Return it untouched rather than inventing an
            # address — a visibly wrong From is debuggable, a silently invented
            # one is not.
            return self._settings.smtp_from
        return formataddr((name, address))


__all__ = ["TIMEOUT_S", "Mailer", "SendResult"]
