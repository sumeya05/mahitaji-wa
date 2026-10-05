"""
The printable Sales Order a customer can download for one of their orders.

Built with ReportLab (``pip install reportlab``). The import is done inside
``build_order_pdf`` so the rest of the site keeps working where the package is
not installed; the view then explains that the PDF is unavailable.
"""
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import timezone

from .models import plain_number, vat_included

LOGO = 'assets/logos/logo_sa.png'


class PdfUnavailable(Exception):
    """ReportLab is not installed on this server."""


def money(value):
    amount = Decimal(value or 0)
    return f"KSh {amount:,.2f}"


def build_order_pdf(order):
    """Return the Sales Order for ``order`` as PDF bytes."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise PdfUnavailable(str(exc)) from exc

    site = settings.SITE_INFO
    navy, line, muted = colors.HexColor('#0a1931'), colors.HexColor('#dce7f1'), colors.HexColor('#5f7a98')
    base = getSampleStyleSheet()['Normal']
    normal = ParagraphStyle('normal', parent=base, fontName='Helvetica', fontSize=9, leading=12.5, textColor=colors.HexColor('#17304d'))
    small = ParagraphStyle('small', parent=normal, fontSize=8, leading=11, textColor=muted)
    label = ParagraphStyle('label', parent=small, fontName='Helvetica-Bold', fontSize=7.5, leading=10)
    right = ParagraphStyle('right', parent=normal, alignment=TA_RIGHT)
    title = ParagraphStyle('title', parent=right, fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=navy)
    company = ParagraphStyle('company', parent=normal, fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=navy)

    def para(text, style=normal):
        # Customer-typed text is escaped; ReportLab paragraphs read a small XML dialect.
        text = str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>')
        return Paragraph(text, style)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Sales Order {order.order_number}", author=site['legal_name'],
    )
    width = doc.width
    story = []

    # --- letterhead ---------------------------------------------------------
    seller = [Paragraph(site['legal_name'], company), para(site['address'], small), para(site['po_box'], small),
              para(f"{site['phone']} · {site['email']}", small)]
    if site.get('kra_pin'):
        seller.append(para(f"KRA PIN: {site['kra_pin']}", small))
    logo_path = finders.find(LOGO)
    logo = Image(logo_path, width=16 * mm, height=16 * mm) if logo_path else ''
    placed = timezone.localtime(order.created_at).strftime('%d %b %Y, %H:%M')
    heading = [Paragraph('SALES ORDER', title), para(order.order_number, right), para(f"Placed {placed}", ParagraphStyle('r2', parent=small, alignment=TA_RIGHT))]
    story.append(Table([[logo, seller, heading]], colWidths=[20 * mm, width * 0.5, width - 20 * mm - width * 0.5],
                       style=TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                         ('RIGHTPADDING', (0, 0), (-1, -1), 0)])))
    story.append(Spacer(1, 6 * mm))

    # --- customer and order facts -------------------------------------------
    profile = order.customer
    customer = [Paragraph('DELIVER TO', label), para(order.full_name or '—')]
    if profile and profile.business_name:
        customer.append(para(profile.business_name))
    customer.append(para(f"{order.address or ''}{', ' + order.city if order.city else ''}"))
    if order.phone:
        customer.append(para(order.phone))
    if order.email:
        customer.append(para(order.email))
    if profile and profile.tax_id:
        customer.append(para(f"KRA PIN: {profile.tax_id}"))

    payment = order.latest_payment
    facts = [Paragraph('ORDER', label), para(f"Status: {order.get_status_display()}"),
             para(f"Payment: {order.get_payment_method_display()}"),
             para("Paid" + (f" on {timezone.localtime(order.paid_at):%d %b %Y}" if order.paid_at else '') if order.is_paid else "Not yet paid")]
    if payment and payment.is_success and payment.receipt_number:
        facts.append(para(f"M-Pesa receipt: {payment.receipt_number}"))
    if order.notes:
        facts += [Spacer(1, 2 * mm), Paragraph('NOTES', label), para(order.notes)]
    story.append(Table([[customer, facts]], colWidths=[width * 0.55, width * 0.45],
                       style=TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (0, 0), (-1, -1), 0.6, line),
                                         ('LINEAFTER', (0, 0), (0, 0), 0.6, line), ('TOPPADDING', (0, 0), (-1, -1), 8),
                                         ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('LEFTPADDING', (0, 0), (-1, -1), 10)])))
    story.append(Spacer(1, 6 * mm))

    # --- lines --------------------------------------------------------------
    rows = [[Paragraph(h, label) for h in ('#', 'ITEM CODE', 'DESCRIPTION', 'UNIT', 'QTY', 'UNIT PRICE', 'VAT', 'AMOUNT')]]
    for number, item in enumerate(order.items.all(), start=1):
        product = item.product
        rows.append([
            para(number), para(product.item_code or '—'), para(product.name), para(product.pack_size or '—'),
            para(item.quantity, right), para(f"{item.price_at_purchase:,.2f}", right),
            para(f"{plain_number(product.vat_rate)}%", right), para(f"{item.subtotal:,.2f}", right),
        ])
    columns = [8 * mm, 22 * mm, None, 18 * mm, 12 * mm, 24 * mm, 13 * mm, 26 * mm]
    columns[2] = width - sum(c for c in columns if c)
    story.append(Table(rows, colWidths=columns, repeatRows=1, style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f6fafd')), ('LINEBELOW', (0, 0), (-1, -1), 0.5, line),
        ('LINEABOVE', (0, 0), (-1, 0), 0.5, line), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (4, 0), (-1, 0), 'RIGHT'),
    ])))
    story.append(Spacer(1, 4 * mm))

    # --- totals -------------------------------------------------------------
    totals = [['Subtotal', money(order.subtotal_amount)]]
    if order.discount_amount:
        totals.append([f"Discount ({order.coupon_code}, {plain_number(order.discount_percent)}%)", '− ' + money(order.discount_amount)])
    totals += [['Net amount (excl. VAT)', money(order.net_amount)], ['VAT (included)', money(order.vat_amount)],
               ['Total (incl. VAT)', money(order.total_amount)]]
    last = len(totals) - 1
    story.append(Table(
        [['', Table(totals, colWidths=[52 * mm, 34 * mm], style=TableStyle([
            ('FONT', (0, 0), (-1, -1), 'Helvetica', 9), ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('TEXTCOLOR', (0, 0), (0, -1), muted), ('LINEABOVE', (0, last), (-1, last), 0.8, navy),
            ('FONT', (0, last), (-1, last), 'Helvetica-Bold', 10.5), ('TEXTCOLOR', (0, last), (-1, last), navy),
            ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))]],
        colWidths=[width - 86 * mm, 86 * mm], style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]),
    ))
    story.append(Spacer(1, 8 * mm))

    # --- VAT summary and small print ----------------------------------------
    by_rate = {}
    share = (order.total_amount / order.subtotal_amount) if order.subtotal_amount else Decimal('1')
    for item in order.items.all():
        by_rate[item.product.vat_rate] = by_rate.get(item.product.vat_rate, Decimal('0')) + item.subtotal * share
    summary = '; '.join(
        f"{plain_number(rate)}% on {money(gross - vat_included(gross, rate))} = {money(vat_included(gross, rate))}"
        for rate, gross in sorted(by_rate.items(), reverse=True)
    )
    if summary:
        story.append(para(f"VAT analysis: {summary}.", small))
    story.append(para("Prices include VAT. This Sales Order confirms what you ordered; it is not a tax invoice. "
                      "The tax invoice is issued with your delivery.", small))
    story.append(para(f"Questions about this order? Call {site['phone']} or email {site['email']} and quote {order.order_number}.", small))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(document.leftMargin, 9 * mm, f"{site['legal_name']} · {site['hours']}")
        canvas.drawRightString(A4[0] - document.rightMargin, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
