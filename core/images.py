"""
Product photos arriving in bulk: files uploaded in the admin (loose or zipped) and the
``image`` column of a product CSV (a filename already in media/products/, or a URL).

Every image is checked with Pillow, shrunk to at most MAX_SIDE pixels on its longer side
and saved under media/products/<name>. Nothing that is not a real image is ever written.
"""
import io
import ipaddress
import os
import re
import socket
import zipfile
from urllib.parse import urljoin, urlparse

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from PIL import Image, UnidentifiedImageError

FOLDER = 'products'
IMAGE_EXTENSIONS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP', '.gif': 'GIF'}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1600
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_TOTAL = 600 * 1024 * 1024
FETCH_TIMEOUT = 10
MAX_FETCH_REDIRECTS = 3


class ImageProblem(ValueError):
    """The file is not an image we can use; the message is safe to show an admin."""


def image_name(filename):
    """``products/<safe-stem><ext>`` for a filename, or None when the extension is not an image's."""
    stem, ext = os.path.splitext(os.path.basename(filename))
    ext = ext.lower()
    if ext not in IMAGE_EXTENSIONS or not stem:
        return None
    return f"{FOLDER}/{get_valid_filename(stem)}{ext}"


def prepare(data, filename):
    """Validate ``data`` as an image and return (bytes, ext) shrunk to MAX_SIDE, same format."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageProblem(f"{filename}: larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    name = image_name(filename)
    if not name:
        raise ImageProblem(f"{filename}: not a .jpg, .png, .webp or .gif file")
    ext = os.path.splitext(name)[1]
    try:
        Image.open(io.BytesIO(data)).verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageProblem(f"{filename}: not a valid image") from exc
    fmt = IMAGE_EXTENSIONS[ext]
    if fmt == 'GIF':
        return data, ext  # animated GIFs are kept as they are
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    elif image.format == fmt:
        return data, ext  # already small enough: keep the original bytes untouched
    if fmt == 'JPEG' and image.mode not in ('RGB', 'L'):
        image = image.convert('RGB')
    out = io.BytesIO()
    options = {'quality': 85, 'optimize': True} if fmt in ('JPEG', 'WEBP') else {'optimize': True}
    image.save(out, fmt, **options)
    return out.getvalue(), ext


def store(filename, data):
    """Save an uploaded/fetched image under media/products/ (replacing a file of the same name)."""
    data, ext = prepare(data, filename)
    name = image_name(filename)
    if default_storage.exists(name):
        default_storage.delete(name)
    return default_storage.save(name, ContentFile(data))


def resolve(reference):
    """
    The storage name for an image already in media/products/, given how an admin might write
    it in a CSV: ``bd001.jpg``, ``products/bd001.jpg``, ``media/products/bd001.jpg`` or
    ``/media/products/bd001.jpg``. None when no such file exists.
    """
    name = image_name(reference)
    if name and default_storage.exists(name):
        return name
    return None


def _addresses_of(host):
    """Every address ``host`` resolves to (patched in tests)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def check_public_url(url):
    """
    Only fetch from public web servers. The import runs on the server, so a URL pointing at
    127.0.0.1, the private network or the cloud metadata address would otherwise let a CSV
    reach services that are supposed to be unreachable from outside.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ImageProblem(f"{url}: not an http(s) address")
    try:
        addresses = _addresses_of(parsed.hostname)
    except (socket.gaierror, UnicodeError) as exc:
        raise ImageProblem(f"{url}: host could not be resolved") from exc
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ImageProblem(f"{url}: points at a private or local address")
    return parsed


def fetch(url):
    """Download an image from ``url`` and return (bytes, filename)."""
    parsed = check_public_url(url)
    try:
        for _ in range(MAX_FETCH_REDIRECTS + 1):
            # Redirects are followed by hand so every hop gets the same public-address check.
            with requests.get(url, timeout=FETCH_TIMEOUT, stream=True, allow_redirects=False,
                              headers={'User-Agent': 'Mahitaji catalogue import'}) as response:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('Location'):
                    url = urljoin(url, response.headers['Location'])
                    parsed = check_public_url(url)
                    continue
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                data = b''
                for chunk in response.iter_content(64 * 1024):
                    data += chunk
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ImageProblem(f"{url}: larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
                break
        else:
            raise ImageProblem(f"{url}: too many redirects")
    except requests.RequestException as exc:
        raise ImageProblem(f"{url}: could not be downloaded ({exc.__class__.__name__})") from exc
    filename = os.path.basename(parsed.path)
    if not image_name(filename):
        ext = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}.get(content_type)
        if not ext:
            raise ImageProblem(f"{url}: not an image (server says {content_type or 'unknown type'})")
        filename = (os.path.splitext(filename)[0] or 'image') + ext
    return data, filename


def unpack(uploaded_files):
    """Yield (filename, bytes) for each image in the uploads, looking inside .zip files."""
    for upload in uploaded_files:
        if upload.name.lower().endswith('.zip'):
            try:
                archive = zipfile.ZipFile(upload)
            except zipfile.BadZipFile:
                yield upload.name, None
                continue
            entries = [e for e in archive.infolist() if not e.is_dir() and '__MACOSX' not in e.filename]
            if len(entries) > MAX_ZIP_ENTRIES or sum(e.file_size for e in entries) > MAX_ZIP_TOTAL:
                raise ImageProblem(f"{upload.name}: too large to unpack ({len(entries)} files)")
            for entry in entries:
                filename = os.path.basename(entry.filename)
                if filename and not filename.startswith('.'):
                    # Read at most the limit plus one byte: the size in the zip's own table is
                    # whatever the zip's author wrote there, so it is not relied on.
                    with archive.open(entry) as member:
                        yield filename, member.read(MAX_IMAGE_BYTES + 1)
        else:
            yield upload.name, upload.read()


_CODE_SPLIT = re.compile(r'[\s_\-()]+')


def codes_from(filename):
    """Candidate item codes in a filename: ``BID283.jpg`` -> BID283; ``bid283_front.jpg`` -> BID283."""
    stem = os.path.splitext(os.path.basename(filename))[0].strip()
    candidates = [stem] + [part for part in _CODE_SPLIT.split(stem) if part]
    seen, out = set(), []
    for candidate in candidates:
        key = candidate.upper()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def attach(uploaded_files, replace_existing=True):
    """
    Save every image and attach it to the product whose item code is in the filename.
    Returns a report: linked [(product, name)], skipped [(product, name)] (already had a photo),
    unmatched [name] (saved, no product with that code) and errors [message].
    """
    from .models import Product

    report = {'linked': [], 'skipped': [], 'unmatched': [], 'errors': []}
    try:
        for filename, data in unpack(uploaded_files):
            if data is None:
                report['errors'].append(f"{filename}: not a valid zip file")
                continue
            try:
                name = store(filename, data)
            except ImageProblem as exc:
                report['errors'].append(str(exc))
                continue
            product = None
            for code in codes_from(filename):
                product = Product.objects.filter(item_code__iexact=code).first()
                if product:
                    break
            if product is None:
                report['unmatched'].append(name)
            elif product.image and not replace_existing:
                report['skipped'].append((product, name))
            else:
                product.image.name = name
                product.save(update_fields=['image', 'last_sync_time'])
                report['linked'].append((product, name))
    except ImageProblem as exc:
        report['errors'].append(str(exc))
    return report
