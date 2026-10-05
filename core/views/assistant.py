"""
AI shopping assistant endpoint. The behaviour (rate limiting, deterministic
answers, the language model call and logging) lives in ``core/assistant.py``;
this view only validates the request and shapes the JSON reply.
"""
import logging

from django.conf import settings
from django.views.decorators.http import require_POST

from .. import assistant
from ._common import json_error, json_ok, request_data

logger = logging.getLogger(__name__)


@require_POST
def ai_assistant_chat(request):
    data = request_data(request)
    message = (data.get('message') or '').strip()
    if not message:
        return json_error("Say something first.")
    if len(message) > settings.ASSISTANT_MAX_MESSAGE_LENGTH:
        return json_error(f"Please keep messages under {settings.ASSISTANT_MAX_MESSAGE_LENGTH} characters.")
    try:
        reply = assistant.answer(request, message)  # context comes from the server-side log, not the browser
    except assistant.RateLimited:
        return json_error("You're sending messages very quickly. Please wait a few minutes and try again.", status=429)
    return json_ok(reply=reply.text, products=reply.product_links(), handled_by=reply.handled_by)
