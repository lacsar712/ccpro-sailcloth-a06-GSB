from rest_framework import serializers

from .models import BladeCard, ClothRoll, DipRun, Loft
from .rules import BladeRuleError, can_mark_roll_cured, register_dip_consuming_blade


class LoftSerializer(serializers.ModelSerializer):
    rollCount = serializers.SerializerMethodField()

    class Meta:
        model = Loft
        fields = ("id", "name", "location", "notes", "rollCount", "created_at")
        read_only_fields = ("id", "rollCount", "created_at")

    def get_rollCount(self, obj):
        if hasattr(obj, "roll_count"):
            return obj.roll_count
        return obj.rolls.count()


class ClothRollSerializer(serializers.ModelSerializer):
    loftId = serializers.PrimaryKeyRelatedField(source="loft", queryset=Loft.objects.all())
    rollCode = serializers.CharField(source="roll_code")
    fabricWeightGsm = serializers.IntegerField(source="fabric_weight_gsm", required=False)
    loftName = serializers.CharField(source="loft.name", read_only=True)

    class Meta:
        model = ClothRoll
        fields = (
            "id",
            "loftId",
            "loftName",
            "rollCode",
            "status",
            "fabricWeightGsm",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "loftName", "created_at", "updated_at")

    def validate(self, attrs):
        loft = attrs.get("loft") or getattr(self.instance, "loft", None)
        roll_code = attrs.get("roll_code") or getattr(self.instance, "roll_code", None)
        if loft and roll_code:
            qs = ClothRoll.objects.filter(loft=loft, roll_code=roll_code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"rollCode": "同一帆布间卷号必须唯一"})

        new_status = attrs.get("status")
        if new_status == ClothRoll.STATUS_CURED:
            roll = self.instance
            if roll is None:
                raise serializers.ValidationError(
                    {"status": "新建布卷不能直接设为已固化"}
                )
            # 合并未提交字段到临时视角：用当前实例校验
            ok, msg = can_mark_roll_cured(roll)
            if not ok:
                raise serializers.ValidationError({"status": msg})
        return attrs


class DipRunSerializer(serializers.ModelSerializer):
    rollId = serializers.PrimaryKeyRelatedField(
        source="roll", queryset=ClothRoll.objects.all()
    )
    startedAt = serializers.DateTimeField(source="started_at")
    resinPct = serializers.DecimalField(source="resin_pct", max_digits=5, decimal_places=2)
    cureHours = serializers.DecimalField(
        source="cure_hours",
        max_digits=6,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    rollCode = serializers.CharField(source="roll.roll_code", read_only=True)
    loftName = serializers.CharField(source="roll.loft.name", read_only=True)

    class Meta:
        model = DipRun
        fields = (
            "id",
            "rollId",
            "rollCode",
            "loftName",
            "startedAt",
            "resinPct",
            "cureHours",
            "notes",
            "created_at",
        )
        read_only_fields = ("id", "rollCode", "loftName", "created_at")

    def create(self, validated_data):
        try:
            return register_dip_consuming_blade(
                roll_id=validated_data["roll"].pk,
                started_at=validated_data["started_at"],
                resin_pct=validated_data["resin_pct"],
                cure_hours=validated_data.get("cure_hours"),
                notes=validated_data.get("notes", ""),
            )
        except BladeRuleError as exc:
            raise serializers.ValidationError({"detail": str(exc)})


class BladeCardSerializer(serializers.ModelSerializer):
    loftId = serializers.PrimaryKeyRelatedField(source="loft", queryset=Loft.objects.all())
    bladeBatchNo = serializers.CharField(source="blade_batch_no", max_length=60)
    remainingUses = serializers.IntegerField(source="remaining_uses", min_value=0)
    voidedAt = serializers.DateTimeField(source="voided_at", read_only=True, allow_null=True)
    loftName = serializers.CharField(source="loft.name", read_only=True)
    isActive = serializers.SerializerMethodField()

    class Meta:
        model = BladeCard
        fields = (
            "id",
            "loftId",
            "loftName",
            "bladeBatchNo",
            "remainingUses",
            "isActive",
            "voidedAt",
            "created_at",
        )
        read_only_fields = ("id", "loftName", "isActive", "voidedAt", "created_at")

    def get_isActive(self, obj):
        return obj.voided_at is None

    def validate(self, attrs):
        remaining = attrs.get("remaining_uses")
        if remaining is not None and remaining < 0:
            raise serializers.ValidationError(
                {"remainingUses": "剩余刀次必须为非负整数"}
            )
        if self.instance is None:
            loft = attrs.get("loft")
            if loft and BladeCard.objects.filter(
                loft=loft, voided_at__isnull=True
            ).exists():
                raise serializers.ValidationError(
                    {"loftId": "该帆布间已有现行刀片寿命卡，请先作废旧卡再新建"}
                )
        return attrs
