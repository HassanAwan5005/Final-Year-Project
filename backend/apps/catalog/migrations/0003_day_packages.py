"""
Add a 1 Day and a 2 Day package for every photographer on the standard tiers.

Priced from their 6-hour "Signature" package (the 1x tier): 2.5x for one day
and 4.5x for two. Photographers can edit them like any other service. Anyone
already offering a day-long package is left alone.
"""

from decimal import Decimal

from django.db import migrations

TIERS = [
    # hours, title, price multiplier, photos, length, display order
    (24, "1 Day", Decimal("2.5"), 300, "1 full day", 3),
    (48, "2 Day", Decimal("4.5"), 550, "2 full days", 4),
]


def add_day_packages(apps, schema_editor):
    Service = apps.get_model("catalog", "Service")

    has_one = set(
        Service.objects.filter(
            duration_hours__gte=24, is_deleted=False
        ).values_list("photographer_id", flat=True)
    )
    standard = Service.objects.filter(
        title__startswith="Signature ", title__endswith=" Package",
        duration_hours=6, is_active=True, is_deleted=False,
    ).select_related("category")

    rows = []
    for base in standard:
        if base.photographer_id in has_one:
            continue
        has_one.add(base.photographer_id)
        name = base.category.name
        for hours, title, multiplier, photos, length, order in TIERS:
            rows.append(
                Service(
                    photographer_id=base.photographer_id,
                    category_id=base.category_id,
                    title=f"{title} {name} Package",
                    description=(
                        f"{length} of {name.lower()} coverage with {photos} "
                        f"professionally edited photographs, delivered through a "
                        f"private online gallery."
                    ),
                    price=(base.price * multiplier).quantize(Decimal("1")),
                    pricing_unit="FIXED",
                    duration_hours=hours,
                    edited_photos_count=photos,
                    delivery_days=21,
                    includes=[
                        f"{length} coverage",
                        f"{photos} edited photos",
                        "Private online gallery",
                        "Print release",
                        "Second photographer",
                        "Same-day previews",
                    ],
                    display_order=order,
                    is_active=True,
                )
            )
    Service.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(add_day_packages, migrations.RunPython.noop),
    ]
