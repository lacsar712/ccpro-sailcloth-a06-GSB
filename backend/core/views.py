from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BladeCard, ClothRoll, DipRun, Loft
from .serializers import (
    BladeCardSerializer,
    ClothRollSerializer,
    DipRunSerializer,
    LoftSerializer,
)


class LoftViewSet(viewsets.ModelViewSet):
    queryset = Loft.objects.annotate(roll_count=Count("rolls")).all()
    serializer_class = LoftSerializer


class ClothRollViewSet(viewsets.ModelViewSet):
    serializer_class = ClothRollSerializer

    def get_queryset(self):
        qs = ClothRoll.objects.select_related("loft").all()
        loft_id = self.request.query_params.get("loftId")
        status = self.request.query_params.get("status")
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        if status:
            qs = qs.filter(status=status)
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


class BladeCardViewSet(viewsets.ModelViewSet):
    """刀片寿命卡：任何登录用户可建卡，作废仅管理员。"""

    serializer_class = BladeCardSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = BladeCard.objects.select_related("loft").all()
        loft_id = self.request.query_params.get("loftId")
        state = self.request.query_params.get("state")
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        if state == "active":
            qs = qs.filter(voided_at__isnull=True)
        elif state == "voided":
            qs = qs.filter(voided_at__isnull=False)
        return qs

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        user = request.user
        if not (user.is_superuser or getattr(user, "role", None) == user.ROLE_ADMIN):
            return Response(
                {"detail": "仅管理员可作废刀片寿命卡"},
                status=status.HTTP_403_FORBIDDEN,
            )
        card = self.get_object()
        if card.voided_at is not None:
            return Response(
                {"detail": "该刀片寿命卡已作废，刀次不可再使用"},
                status=status.HTTP_400_BAD_REQUEST,
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
    }
    return Response(data)
