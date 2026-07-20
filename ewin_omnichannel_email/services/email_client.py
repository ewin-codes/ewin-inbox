import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate

import imaplib

from odoo.tools import html2plaintext


class EmailError(Exception):
    def __init__(self, message, retriable=True):
        self.retriable = retriable
        super().__init__(message)


class EmailClient:
    def __init__(self, account, timeout=20):
        self.account = account
        self.timeout = timeout
        self._imap = None

    # ---- IMAP ----
    @staticmethod
    def _safe_close(conn):
        if conn is None:
            return
        for method in ("logout", "close", "quit"):
            fn = getattr(conn, method, None)
            if fn is None:
                continue
            try:
                fn()
                return
            except Exception:  # noqa: BLE001
                continue

    def connect_imap(self):
        acc = self.account
        host = acc.email_imap_host
        port = acc.email_imap_port or 993
        login = acc.email_address
        password = acc.sudo().email_password or ""
        conn = None
        try:
            if acc.email_imap_ssl:
                conn = imaplib.IMAP4_SSL(host, port, timeout=self.timeout)
            else:
                conn = imaplib.IMAP4(host, port, timeout=self.timeout)
                conn.starttls(ssl.create_default_context())
            conn.login(login, password)
            typ, data = conn.select(acc.email_folder or "INBOX")
            if typ != "OK":
                raise EmailError(
                    f"Cannot select folder {acc.email_folder or 'INBOX'}: {data}",
                    retriable=False)
        except EmailError:
            self._safe_close(conn)
            raise
        except (imaplib.IMAP4.error, OSError) as err:
            self._safe_close(conn)
            raise EmailError(f"IMAP connect/login failed: {err}", retriable=True)
        self._imap = conn
        return conn

    def fetch_unseen(self):
        conn = self._imap
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        out = []
        for uid in data[0].split():
            typ, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            out.append((uid, msg_data[0][1]))
        return out

    def mark_seen(self, uid):
        self._imap.store(uid, "+FLAGS", "\\Seen")

    def logout(self):
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
            self._imap = None

    # ---- SMTP ----
    @staticmethod
    def _first_ipv4(host, port):
        """Resolve host to a single IPv4 address. Some mailbox hosts publish an
        AAAA record the server cannot route to (the prod container has no IPv6),
        which makes socket.create_connection intermittently pick IPv6 first and
        fail with [Errno 99] Cannot assign requested address — stalling the send
        for a full timeout before it retries. Connecting to a resolved IPv4
        address makes the outbound path deterministic."""
        infos = socket.getaddrinfo(
            host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise EmailError(f"no IPv4 address for {host}", retriable=True)
        return infos[0][4][0]

    def _open_smtp(self):
        """Open and authenticate an SMTP connection over TLS, forcing IPv4 on
        the STARTTLS path (see _first_ipv4). The hostname is restored on the
        server object before STARTTLS so SNI and certificate validation still
        run against the real host, not the IP. Returns a logged-in server; the
        caller owns quit(). Raises raw smtplib/OSError exceptions (plus the TLS
        guard's EmailError) for callers to classify."""
        acc = self.account
        host = acc.email_smtp_host
        port = acc.email_smtp_port or 587
        if acc.email_smtp_security not in ("starttls", "ssl"):
            raise EmailError(
                "SMTP requires STARTTLS or SSL/TLS; refusing plaintext auth.",
                retriable=False)
        context = ssl.create_default_context()
        server = None
        try:
            if acc.email_smtp_security == "ssl":
                # SMTP_SSL wraps the socket during connect using the connect
                # host as server_hostname, so we cannot swap in an IP without
                # breaking cert validation; rely on create_connection's
                # IPv6->IPv4 fallback here (465/SSL is not used on prod).
                server = smtplib.SMTP_SSL(
                    host, port, timeout=self.timeout, context=context)
            else:
                ip = self._first_ipv4(host, port)
                server = smtplib.SMTP(timeout=self.timeout)
                server.connect(ip, port)
                server._host = host  # restore hostname for STARTTLS SNI/cert
                server.starttls(context=context)
            server.login(acc.email_address, acc.sudo().email_password or "")
            return server
        except Exception:
            self._safe_close(server)
            raise

    def send(self, from_addr, from_name, to_addr, subject, html_body,
             message_id, in_reply_to=None, references=None, attachments=None):
        msg = EmailMessage()
        msg["From"] = formataddr((from_name or "", from_addr))
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        msg["Date"] = formatdate(localtime=True)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        text = html2plaintext(html_body) if html_body else ""
        msg.set_content(text or " ")
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        for att in (attachments or []):
            mimetype = att.mimetype or "application/octet-stream"
            maintype, _, subtype = mimetype.partition("/")
            msg.add_attachment(
                att.raw or b"", maintype=maintype or "application",
                subtype=subtype or "octet-stream", filename=att.name or "file")
        server = None
        try:
            server = self._open_smtp()
            server.send_message(msg)
        except EmailError:
            raise
        except (smtplib.SMTPAuthenticationError,
                smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused) as err:
            self._safe_close(server)
            raise EmailError(f"SMTP rejected the message: {err}", retriable=False)
        except (smtplib.SMTPException, OSError) as err:
            self._safe_close(server)
            raise EmailError(f"SMTP send failed: {err}", retriable=True)
        # message already accepted by the server; a failing quit must not
        # trigger a retry (that would resend a duplicate).
        try:
            server.quit()
        except Exception:  # noqa: BLE001 - best-effort close after delivery
            pass
        return message_id

    def check_smtp(self):
        """Open the SMTP connection and authenticate WITHOUT sending, so the
        "Check Connection" button can verify the outbound path too. Raises
        EmailError (non-retriable) describing what failed."""
        server = None
        try:
            server = self._open_smtp()
        except EmailError:
            raise
        except smtplib.SMTPAuthenticationError as err:
            self._safe_close(server)
            raise EmailError(f"authentication failed ({err})", retriable=False)
        except (smtplib.SMTPException, OSError) as err:
            self._safe_close(server)
            raise EmailError(
                f"cannot reach the SMTP server ({err})", retriable=False)
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
        return True
