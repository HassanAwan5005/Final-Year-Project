"""
Open every weekday for every photographer.

New photographers used to get Sunday off automatically, but functions are often
held on Sundays. Photographers can still turn a weekday off themselves.
"""

from django.db import migrations


def open_every_weekday(apps, schema_editor):
    AvailabilityRule = apps.get_model("availability", "AvailabilityRule")
    AvailabilityRule.objects.filter(is_available=False).update(is_available=True)


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(open_every_weekday, migrations.RunPython.noop),
    ]
