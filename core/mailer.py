"""
Sending email without making the customer wait for the mail server.

There is no task queue on the one-server deployment, so a message is handed to a short-lived
thread (settings.EMAIL_IN_BACKGROUND). The message is fully rendered before the thread
starts and sending touches no database connection, so nothing request-bound leaks into it.
"""
import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


def _deliver(message, label):
    try:
        message.send(fail_silently=False)
    except Exception:  # noqa: BLE001 - logged, never raised into a request
        logger.exception("Could not send email: %s", label)


def send(message, label=''):
    """Send ``message`` (an EmailMessage), in the background when so configured."""
    label = label or message.subject
    if settings.EMAIL_IN_BACKGROUND:
        threading.Thread(target=_deliver, args=(message, label), name=f'email:{label}'[:60], daemon=True).start()
    else:
        _deliver(message, label)
