"""帆布浸渍防水台业务规则。"""

from __future__ import annotations

from decimal import Decimal

from .models import BladeCard, ClothRoll, DipRun

MIN_CURE_HOURS_FOR_CURED = Decimal("12")


class BladeCardError(Exception):
    """刀片寿命卡业务校验失败；消息为中文，直接透传给前端。"""


def active_blade_card(loft_id) -> BladeCard | None:
    """帆布间的现行（未作废）刀片寿命卡。"""
    return BladeCard.objects.filter(loft_id=loft_id, voided_at__isnull=True).first()


def consume_blade_use(roll: ClothRoll) -> BladeCard:
    """
    登记浸渍的刀次扣减。必须在 transaction.atomic() 内调用：
    行级锁定该卷所在帆布间的现行刀片卡，校验剩余刀次 >= 1 后减 1。
    并发下第二个请求会阻塞在锁上，读到扣减后的值，从而被正确挡住。
    """
    card = (
        BladeCard.objects.select_for_update()
        .filter(loft_id=roll.loft_id, voided_at__isnull=True)
        .first()
    )
    if card is None:
        raise BladeCardError(
            f"帆布间「{roll.loft.name}」没有现行刀片寿命卡，不能登记浸渍"
        )
    if card.remaining_uses < 1:
        raise BladeCardError(
            f"刀片批号 {card.blade_batch} 剩余刀次为 0，不能登记浸渍，请更换新卡"
        )
    card.remaining_uses = card.remaining_uses - 1
    card.save(update_fields=["remaining_uses"])
    return card


def latest_dip_run(roll: ClothRoll) -> DipRun | None:
    return roll.dip_runs.order_by("-started_at", "-id").first()


def can_mark_roll_cured(roll: ClothRoll) -> tuple[bool, str]:
    """
    布卷转为「已固化」(cured) 的前提：
    最近一条浸渍记录的固化时长已记录，且 >= 12 小时。
    """
    latest = latest_dip_run(roll)
    if latest is None:
        return False, "该布卷尚无浸渍记录，不能标记为已固化"
    if latest.cure_hours is None:
        return False, "最近浸渍记录尚未填写固化时长，不能标记为已固化"
    if latest.cure_hours < MIN_CURE_HOURS_FOR_CURED:
        return (
            False,
            f"最近浸渍固化时长 {latest.cure_hours} 小时低于 {MIN_CURE_HOURS_FOR_CURED} 小时，不能标记为已固化",
        )
    return True, ""
