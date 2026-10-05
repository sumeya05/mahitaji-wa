"""
ChatMessage.session_key used to hold the visitor's raw session key, which is the session
cookie itself. It now holds a one-way fingerprint (core.assistant.session_fingerprint).
Replace the raw keys already logged. Raw keys are 32 characters; fingerprints are 40, so
the migration can tell them apart and is safe to run more than once.
"""
import hashlib

from django.db import migrations


def hash_session_keys(apps, schema_editor):
    ChatMessage = apps.get_model('core', 'ChatMessage')
    for row in ChatMessage.objects.exclude(session_key='').exclude(session_key__regex=r'^[0-9a-f]{40}$').iterator():
        row.session_key = hashlib.sha256(row.session_key.encode()).hexdigest()[:40]
        row.save(update_fields=['session_key'])


class Migration(migrations.Migration):
    dependencies = [('core', '0026_rename_old_price_to_old_retail_price')]
    operations = [migrations.RunPython(hash_session_keys, migrations.RunPython.noop)]
