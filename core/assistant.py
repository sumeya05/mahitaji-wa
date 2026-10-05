"""
The Mahitaji shopping assistant.

Most customer questions do not need a language model, so they are answered
deterministically and instantly from the database first:

1. order status  - signed-in customers asking about their orders
2. catalogue     - price / stock / availability questions matched to products
3. FAQ           - delivery, payment, returns, opening hours, contact details
4. LLM           - anything else, with the recent conversation and matching
                   products as context (Gemini via the ``google-genai`` SDK)
5. fallback      - when no API key is configured or the model is unavailable

Every exchange is rate-limited per visitor, capped per day for the paid model,
and logged to ``ChatMessage`` so the questions customers really ask can be
reviewed in the admin.
"""
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

from . import throttle
from django.db.models import Q
from django.utils import timezone

from .cart import price_tier_for
from .models import ChatMessage, Order, Product

logger = logging.getLogger(__name__)

ORDER_NUMBER_RE = re.compile(r'\bMAH-[A-Z0-9]{8}\b', re.I)
STOP_WORDS = {
    'the', 'and', 'for', 'you', 'your', 'have', 'what', 'whats', 'how', 'much', 'does', 'this', 'that', 'with',
    'can', 'get', 'any', 'are', 'there', 'price', 'prices', 'cost', 'costs', 'stock', 'sell', 'buy', 'want',
    'need', 'please', 'hello', 'hi', 'about', 'tell', 'me', 'do', 'is', 'of', 'in', 'a', 'an', 'to', 'it',
    'much', 'available', 'availability', 'per', 'each', 'ksh', 'kes', 'shilling', 'shillings',
}
PRICE_INTENT = ('price', 'cost', 'how much', 'stock', 'available', 'availab', 'do you have', 'do you sell',
                'in stock', 'offer', 'discount', 'deal')
ORDER_INTENT = ('order', 'delivery status', 'track', 'where is my', 'my parcel', 'my delivery', 'has it shipped')
# Questions asking for a judgement are left to the language model (with the matching
# products as context) instead of the plain catalogue listing.
ADVICE_INTENT = ('suggest', 'recommend', 'best', 'better', 'which', 'compare', 'difference', 'should i',
                 'good for', 'suitable', 'why', 'versus', ' vs ')

FAQ_INTENTS = [
    ('returns', ('return', 'refund', 'damaged', 'expired', 'exchange', 'wrong item', 'faulty')),
    ('payment', ('pay', 'payment', 'mpesa', 'm-pesa', 'm pesa', 'cash on delivery', 'till', 'paybill', 'bank')),
    ('delivery', ('deliver', 'delivery', 'shipping', 'ship', 'how long', 'upcountry', 'nairobi', 'free delivery',
                  'delivery fee', 'delivery charge')),
    ('location', ('where are you', 'location', 'address', 'office', 'pick up', 'pickup', 'collect', 'warehouse',
                  'open', 'hours', 'opening', 'close', 'closing', 'weekend', 'saturday', 'sunday')),
    ('contact', ('call', 'phone', 'whatsapp', 'email', 'contact', 'talk to', 'speak to', 'sales rep', 'agent')),
    ('wholesale', ('wholesale', 'wholesaler', 'business account', 'tier', 'bulk', 'trade price')),
]


@dataclass
class Reply:
    text: str
    products: list = field(default_factory=list)
    handled_by: str = 'llm'

    def product_links(self):
        return [{'id': p.id, 'name': p.name, 'url': p.get_absolute_url()} for p in self.products]


class RateLimited(Exception):
    pass


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def visitor_key(request):
    if request.user.is_authenticated:
        return f'user:{request.user.pk}'
    if request.session.session_key:
        return f'session:{request.session.session_key}'
    return 'ip:' + throttle.client_ip(request)


_bump = throttle.hit


def check_rate_limit(request):
    key = f'assistant:rate:{visitor_key(request)}'
    if not _bump(key, settings.ASSISTANT_RATE_LIMIT, settings.ASSISTANT_RATE_WINDOW):
        raise RateLimited()


def llm_budget_available():
    key = f'assistant:llm:{timezone.localdate().isoformat()}'
    return _bump(key, settings.ASSISTANT_DAILY_LLM_LIMIT, 60 * 60 * 24)


# ---------------------------------------------------------------------------
# Deterministic handlers
# ---------------------------------------------------------------------------
def _money(value):
    return f"KSh {value:,.0f}"


def _order_line(order):
    when = timezone.localtime(order.created_at).strftime('%d %b')
    return (f"Order {order.order_number} ({when}): {order.get_status_display()} · {order.item_count} item(s) · "
            f"{_money(order.total_amount)} · {order.get_payment_method_display()}. Details: {order.get_absolute_url()}")


def _order_status(request, message):
    lowered = message.lower()
    numbers = ORDER_NUMBER_RE.findall(message)
    if not numbers and not any(k in lowered for k in ORDER_INTENT):
        return None
    if not request.user.is_authenticated:
        return Reply("Sign in and I can check your orders for you. You can also track any order from "
                     "My account → My orders.", handled_by='order')
    profile = getattr(request.user, 'customerprofile', None)
    orders = Order.objects.filter(customer=profile).prefetch_related('items') if profile else Order.objects.none()
    if numbers:
        orders = orders.filter(order_number__in=[n.upper() for n in numbers])
        if not orders.exists():
            return Reply(f"I couldn't find {', '.join(n.upper() for n in numbers)} on your account. "
                         "Check the number on your confirmation email, or see all your orders under My account.",
                         handled_by='order')
    orders = list(orders[:3])
    if not orders:
        return Reply("You haven't placed any orders yet. Once you do, ask me here and I'll show the status.",
                     handled_by='order')
    lines = [_order_line(o) for o in orders]
    pending = [o for o in orders if o.can_pay]
    tip = ""
    if pending:
        tip = f"\n{pending[0].order_number} is still awaiting M-Pesa payment; open it to retry the prompt."
    intro = "Here is your latest order:" if len(orders) == 1 else "Here are your latest orders:"
    return Reply(intro + "\n" + "\n".join(lines) + tip, handled_by='order')


def _keywords(message):
    words = [w.strip('?.,!:;"\'()').lower() for w in message.split()]
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS][:6]


def find_products(message, limit=6):
    words = _keywords(message)
    if not words:
        return [], words
    query = Q()
    for word in words:
        query |= Q(name__icontains=word) | Q(brand__name__icontains=word) | Q(category__name__icontains=word)
    qs = Product.objects.active().with_relations().with_stock().filter(query)
    # Products matching more of the words first, then best sellers.
    scored = sorted(
        qs[:40],
        key=lambda p: (-sum(w in f"{p.name} {p.brand.name if p.brand else ''} {p.category.name if p.category else ''}".lower()
                            for w in words), not p.is_best_seller, p.name),
    )
    return scored[:limit], words


def product_lines(products, tier):
    lines = []
    for p in products:
        bits = [f"{p.name} ({p.brand.name if p.brand else 'Mahitaji'}) — {_money(p.price_for(tier))} per {p.pack_size.lower() or 'unit'}"]
        old = p.old_price_for(tier)
        if old:
            bits.append(f"on offer, was {_money(old)}")
        bits.append("in stock" if p.in_stock else "out of stock")
        lines.append("- " + "; ".join(bits) + f"; link: {p.get_absolute_url()}")
    return "\n".join(lines)


def _catalogue(message, products, tier):
    lowered = message.lower()
    if not products or not any(k in lowered for k in PRICE_INTENT):
        return None
    if settings.GEMINI_API_KEY and any(k in lowered for k in ADVICE_INTENT):
        return None  # advisory question: let the model reason over the products
    label = "wholesale" if tier == 'wholesale' else "retail"
    text = f"Here is what I found ({label} prices):\n" + product_lines(products, tier).replace('; link: ', ' — ')
    return Reply(text, products=products, handled_by='catalogue')


def _faq(message):
    lowered = message.lower()
    site = settings.SITE_INFO
    answers = {
        'delivery': (f"Orders placed before 2 pm are delivered across Nairobi the next working day; upcountry routes "
                     f"take 2–3 days. Delivery in Nairobi is free for orders above {_money(site['free_delivery_threshold'])}. "
                     f"You can also collect from {site['address']}."),
        'payment': ("You can pay by M-Pesa (an STK prompt is sent to your phone at checkout) or cash on delivery. "
                    "If an M-Pesa prompt fails you can retry it from the order page."),
        'returns': ("Damaged, expired or incorrectly supplied items are replaced or refunded when reported within "
                    f"48 hours of delivery, with the goods in their original packaging. Call {site['phone']} to start a return."),
        'location': f"We are at {site['address']}. Opening hours: {site['hours']}. Self pick-up is welcome.",
        'contact': f"Call or WhatsApp us on {site['phone']} ({site['whatsapp']}) or email {site['email']}.",
        'wholesale': ("Wholesale prices apply to verified business accounts. Register a business account and our team "
                      f"will upgrade it; until then your cart is charged at retail. Questions: {site['phone']}."),
    }
    for intent, keys in FAQ_INTENTS:
        if any(k in lowered for k in keys):
            return Reply(answers[intent], handled_by='faq')
    return None


# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------
def _system_prompt(request, tier, products):
    site = settings.SITE_INFO
    name = request.user.get_full_name() if request.user.is_authenticated else "a visitor"
    lines = product_lines(products, tier)
    return (
        "You are the Mahitaji Assistant for Mahitaji Enterprises Ltd, an FMCG wholesaler and retailer in Nairobi, Kenya. "
        "Answer briefly (under 80 words) and helpfully in plain text, no markdown. Prices are in Kenyan shillings. "
        "Only quote prices, stock and offers from the catalogue items listed below; never invent products or prices. "
        f"If you are unsure, say so and point the customer to {site['phone']} or {site['email']}. "
        "Only discuss Mahitaji, its products, ordering, delivery and payment; politely decline anything else. "
        f"Delivery: within 24 hours in Nairobi, 2–3 days upcountry, free in Nairobi above {_money(site['free_delivery_threshold'])}; "
        f"self pick-up at {site['address']}, {site['hours']}. Payment: M-Pesa or cash on delivery. "
        f"The customer is {name} on the {tier} price tier. "
        + (f"Relevant catalogue items:\n{lines}" if lines else "No catalogue items matched their message.")
    )


def _generate(system_prompt, history, message):
    """Call Gemini. Kept separate so tests can replace it."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=int(settings.ASSISTANT_TIMEOUT_SECONDS * 1000)),
    )
    contents = [
        types.Content(role='model' if turn['role'] == 'assistant' else 'user', parts=[types.Part.from_text(text=turn['text'])])
        for turn in history
    ]
    contents.append(types.Content(role='user', parts=[types.Part.from_text(text=message)]))
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL.removeprefix('models/'),
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt, max_output_tokens=320, temperature=0.4,
            # We pass no tools; disabling AFC silences the SDK's warning about it.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return (response.text or '').strip()


def clean_history(raw, limit):
    """Keep only well-formed recent turns sent by the browser."""
    turns = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        text = str(item.get('text') or '').strip()[:settings.ASSISTANT_MAX_MESSAGE_LENGTH]
        if role in ('user', 'assistant') and text:
            turns.append({'role': role, 'text': text})
    return turns[-limit:]


def _llm(request, message, history, products, tier):
    site = settings.SITE_INFO
    lines = product_lines(products, tier).replace('; link: ', ' — ')
    if not settings.GEMINI_API_KEY or not llm_budget_available():
        if products:
            return Reply("Here is what I found in our catalogue:\n" + lines, products=products, handled_by='fallback')
        return Reply(f"I can help with products, orders, delivery and payments. Call us on {site['phone']} "
                     "or browse the catalogue for live prices.", handled_by='fallback')
    try:
        text = _generate(_system_prompt(request, tier, products), history, message)
        return Reply(text or "Sorry, I didn't catch that. Could you rephrase?", products=products, handled_by='llm')
    except Exception as exc:  # network, quota, SDK errors: degrade gracefully
        logger.warning("Assistant model request failed: %s", exc)
        if '429' in str(exc) or 'RESOURCE_EXHAUSTED' in str(exc):
            text = "I'm helping a lot of retailers right now. Please try again in about 30 seconds."
        elif products:
            text = "I'm having trouble connecting right now. Meanwhile, here is what matched in our catalogue:\n" + lines
        else:
            text = f"I'm having trouble connecting right now. Please call {site['phone']} and our team will help."
        return Reply(text, products=products, handled_by='fallback')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def answer(request, message, history=None):
    """Answer ``message`` for this visitor and log the exchange. Raises RateLimited."""
    check_rate_limit(request)
    tier = price_tier_for(request.user)
    products, _ = find_products(message)

    reply = _order_status(request, message) or _catalogue(message, products, tier) or _faq(message)
    if reply is None:
        reply = _llm(request, message, clean_history(history, settings.ASSISTANT_HISTORY_TURNS), products, tier)

    try:
        ChatMessage.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_key=request.session.session_key or '',
            message=message,
            reply=reply.text,
            handled_by=reply.handled_by,
            product_ids=[p.id for p in reply.products],
        )
    except Exception:  # logging must never break the chat
        logger.exception("Could not log assistant message")
    return reply
