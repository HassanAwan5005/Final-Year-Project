"""
Recompute every photographer's `base_price` from their services.

`base_price` is the "from Rs X" on every photographer card, and the Explore
budget filter and sort read it. It must equal the cheapest active service —
`services._refresh_base_price` keeps it so on every catalogue edit. Seeded data
skipped that step: services were created at 0.7x–4.5x of the CSV price and
`base_price` was left at the CSV price, so 199 of 201 photographers showed a
"from" price above their cheapest service, and budget searches left out
photographers who did have a shoot within budget.

Same rule as `_refresh_base_price`: the cheapest active, non-deleted service,
or 0 for a photographer with none.
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import Min, Q


def refresh_base_price(apps, schema_editor):
    PhotographerProfile = apps.get_model("profiles", "PhotographerProfile")

    rows = PhotographerProfile.objects.annotate(
        cheapest=Min(
            "services__price",
            filter=Q(services__is_active=True, services__is_deleted=False),
        )
    )
    changed = []
    for profile in rows:
        price = profile.cheapest or Decimal("0.00")
        if profile.base_price != price:
            profile.base_price = price
            changed.append(profile)
    PhotographerProfile.objects.bulk_update(changed, ["base_price"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_day_packages"),
        ("profiles", "0003_alter_photographerprofile_is_approved"),
    ]

    operations = [
        migrations.RunPython(refresh_base_price, migrations.RunPython.noop),
    ]
