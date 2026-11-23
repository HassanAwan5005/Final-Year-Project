"""
Ads no longer need admin approval, so put the ones still waiting live.

"Waiting" is published but not approved, never removed by an admin. An admin
removal leaves the same flags (`is_approved=False`, still published), so the
audit log tells the two apart: an ad with a PRODUCT_REMOVED entry was taken
down on purpose and stays down.
"""

from django.db import migrations


def approve_waiting_listings(apps, schema_editor):
    DigitalProduct = apps.get_model("marketplace", "DigitalProduct")
    AuditLog = apps.get_model("administration", "AuditLog")

    removed = set(
        AuditLog.objects.filter(
            action="PRODUCT_REMOVED", target_type="DigitalProduct"
        ).values_list("target_id", flat=True)
    )
    waiting = DigitalProduct.objects.filter(
        is_published=True, is_approved=False, is_deleted=False
    )
    ids = [pk for pk in waiting.values_list("pk", flat=True) if str(pk) not in removed]
    DigitalProduct.objects.filter(pk__in=ids).update(is_approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0008_product_is_sold"),
        ("administration", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(approve_waiting_listings, migrations.RunPython.noop),
    ]
