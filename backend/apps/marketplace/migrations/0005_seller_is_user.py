"""
Make the seller of a product (and of a sale) a user account instead of a
photographer profile, so buyers can sell in the shop too.

Existing rows are converted in place: each seller id moves from the
photographer profile's id to that profile's user id.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _remap(apps, forward: bool):
    """
    Rewrite every seller id using the profile <-> user mapping.

    Rows are read first and written by primary key, so an id that is both an
    old value and a new value (profile 5 -> user 12, profile 12 -> user 30)
    can never be rewritten twice.
    """
    from collections import defaultdict

    PhotographerProfile = apps.get_model("profiles", "PhotographerProfile")
    pairs = PhotographerProfile._base_manager.values_list("id", "user_id")
    mapping = dict(pairs) if forward else {user: prof for prof, user in pairs}

    for name in ("DigitalProduct", "OrderItem"):
        model = apps.get_model("marketplace", name)
        by_new_id = defaultdict(list)
        for pk, old in model._base_manager.values_list("pk", "seller_id"):
            if old in mapping:
                by_new_id[mapping[old]].append(pk)
        for new_id, pks in by_new_id.items():
            for i in range(0, len(pks), 1000):
                model._base_manager.filter(pk__in=pks[i:i + 1000]).update(
                    seller_id=new_id
                )


def profile_ids_to_user_ids(apps, schema_editor):
    _remap(apps, forward=True)


def user_ids_to_profile_ids(apps, schema_editor):
    _remap(apps, forward=False)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("profiles", "0003_alter_photographerprofile_is_approved"),
        ("marketplace", "0004_alter_digitalproduct_product_type"),
    ]

    operations = [
        # 1. Drop the foreign-key constraints so the ids can be rewritten.
        migrations.AlterField(
            model_name="digitalproduct",
            name="seller",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="products",
                to="profiles.photographerprofile",
            ),
        ),
        migrations.AlterField(
            model_name="orderitem",
            name="seller",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sales",
                to="profiles.photographerprofile",
            ),
        ),
        # 2. Profile id -> user id.
        migrations.RunPython(profile_ids_to_user_ids, user_ids_to_profile_ids),
        # 3. Point the columns at the user table, constraints back on.
        migrations.AlterField(
            model_name="digitalproduct",
            name="seller",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shop_products",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="orderitem",
            name="seller",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shop_sales",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
