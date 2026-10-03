from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .models import BladeCard, ClothRoll, DipRun, Loft
from .rules import BladeCardError, consume_blade_use
from .serializers import (
    BladeCardSerializer,
    ClothRollSerializer,
    DipRunSerializer,
    LoftSerializer,
)


class IsAdminRole(BasePermission):
    message = "仅管理员可执行此操作"

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", None) == user.ROLE_ADMIN
        )


class LoftViewSet(viewsets.ModelViewSet):
    queryset = Loft.objects.annotate(roll_count=Count("rolls")).all()
    serializer_class = LoftSerializer


class ClothRollViewSet(viewsets.ModelViewSet):
    serializer_class = ClothRollSerializer

    def get_queryset(self):
        qs = ClothRoll.objects.select_related("loft").all()
        loft_id = self.request.query_params.get("loftId")
        status_param = self.request.query_params.get("status")
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class DipRunViewSet(viewsets.ModelViewSet):
    serializer_class = DipRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = DipRun.objects.select_related("roll", "roll__loft").all()
        roll_id = self.request.query_params.get("rollId")
        if roll_id:
            qs = qs.filter(roll_id=roll_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        roll = serializer.validated_data["roll"]
        try:
            with transaction.atomic():
                # 锁现行刀片卡并扣 1 刀次；剩余为 0 或无卡时抛中文错误，
                # 整个事务回滚：浸渍记录与布卷状态都不会落库。
                consume_blade_use(roll)
                if roll.status != ClothRoll.STATUS_DIPPING:
                    roll.status = ClothRoll.STATUS_DIPPING
                    roll.save(update_fields=["status", "updated_at"])
                self.perform_create(serializer)
        except BladeCardError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class BladeCardViewSet(viewsets.ModelViewSet):
    """刀片寿命卡：操作工可建卡；作废仅管理员。不提供改/删。"""

    serializer_class = BladeCardSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = BladeCard.objects.select_related("loft").all()
        state = self.request.query_params.get("state")
        loft_id = self.request.query_params.get("loftId")
        if state == "active":
            qs = qs.filter(voided_at__isnull=True)
        elif state == "voided":
            qs = qs.filter(voided_at__isnull=False)
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                self.perform_create(serializer)
        except IntegrityError:
            # 并发建卡撞上「同间现行卡唯一」约束
            return Response(
                {"detail": "该帆布间已有现行刀片寿命卡，不能重复建卡"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def void(self, request, pk=None):
        card = self.get_object()
        if card.voided_at is not None:
            return Response(
                {"detail": "该刀片寿命卡已作废"}, status=status.HTTP_400_BAD_REQUEST
            )
        card.voided_at = timezone.now()
        card.save(update_fields=["voided_at"])
        return Response(self.get_serializer(card).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    data = {
        "loftCount": Loft.objects.count(),
        "rawRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_RAW).count(),
        "dippingRollCount": ClothRoll.objects.filter(
            status=ClothRoll.STATUS_DIPPING
        ).count(),
        "curedRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_CURED).count(),
        "dipRunCount": DipRun.objects.count(),
        "activeBladeCardCount": BladeCard.objects.filter(voided_at__isnull=True).count(),
    }
    return Response(data)
