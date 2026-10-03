from django.db import models


class Loft(models.Model):
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class ClothRoll(models.Model):
    STATUS_RAW = "raw"
    STATUS_DIPPING = "dipping"
    STATUS_CURED = "cured"
    STATUS_CHOICES = [
        (STATUS_RAW, "原布"),
        (STATUS_DIPPING, "浸渍中"),
        (STATUS_CURED, "已固化"),
    ]

    loft = models.ForeignKey(Loft, on_delete=models.CASCADE, related_name="rolls")
    roll_code = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RAW)
    fabric_weight_gsm = models.PositiveIntegerField(default=380)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["loft_id", "roll_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["loft", "roll_code"],
                name="uniq_roll_code_per_loft",
            )
        ]

    def __str__(self):
        return f"{self.loft.name}/{self.roll_code}"


class DipRun(models.Model):
    roll = models.ForeignKey(ClothRoll, on_delete=models.CASCADE, related_name="dip_runs")
    started_at = models.DateTimeField()
    resin_pct = models.DecimalField(max_digits=5, decimal_places=2)
    cure_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Dip@{self.roll_id} {self.started_at}"


class BladeCard(models.Model):
    """刮胶刀片寿命卡：每登记一笔浸渍消耗 1 刀次。"""

    loft = models.ForeignKey(Loft, on_delete=models.CASCADE, related_name="blade_cards")
    blade_batch_no = models.CharField(max_length=60)
    remaining_uses = models.PositiveIntegerField()
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(remaining_uses__gte=0),
                name="blade_card_remaining_non_negative",
            ),
            models.UniqueConstraint(
                fields=["loft"],
                condition=models.Q(voided_at__isnull=True),
                name="uniq_active_blade_card_per_loft",
            ),
        ]

    def __str__(self):
        return f"{self.loft.name}/{self.blade_batch_no} 余{self.remaining_uses}刀次"
