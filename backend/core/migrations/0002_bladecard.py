import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BladeCard",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("blade_batch_no", models.CharField(max_length=60)),
                ("remaining_uses", models.PositiveIntegerField()),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "loft",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blade_cards",
                        to="core.loft",
                    ),
                ),
            ],
            options={"ordering": ["-id"]},
        ),
        migrations.AddConstraint(
            model_name="bladecard",
            constraint=models.CheckConstraint(
                check=models.Q(("remaining_uses__gte", 0)),
                name="blade_card_remaining_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="bladecard",
            constraint=models.UniqueConstraint(
                condition=models.Q(("voided_at__isnull", True)),
                fields=("loft",),
                name="uniq_active_blade_card_per_loft",
            ),
        ),
    ]
