"""帆布浸渍防水台业务规则。"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from .models import BladeCard, ClothRoll, DipRun

MIN_CURE_HOURS_FOR_CURED = Decimal("12")


class BladeRuleError(Exception):
    """刀片寿命卡规则被违反；消息为中文，直接回显给操作工。"""


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


def active_blade_card(loft) -> BladeCard | None:
    """帆布间的现行（未作废）刀片寿命卡，没有则 None。"""
    return loft.blade_cards.filter(voided_at__isnull=True).first()


@transaction.atomic
def register_dip_consuming_blade(
    *, roll_id, started_at, resin_pct, cure_hours=None, notes=""
) -> DipRun:
    """
    登记一笔浸渍，同一事务内依次完成：

    1. 行级锁定并读取该布卷所在帆布间的现行刀片寿命卡；
    2. 剩余刀次须 >= 1，否则抛 BladeRuleError，整个事务回滚；
    3. 写入 DipRun；
    4. 现行卡剩余刀次减 1；
    5. 原布状态的布卷改为「浸渍中」。

    并发登记抢同一间最后 1 刀次时，select_for_update 把两笔事务串行化：
    只有先到的一笔试入库并扣完，后到的一笔试读到 0 被中文挡住。
    """
    roll = ClothRoll.objects.select_related("loft").get(pk=roll_id)
    card = (
        BladeCard.objects.select_for_update()
        .filter(loft=roll.loft, voided_at__isnull=True)
        .first()
    )
    if card is None:
        raise BladeRuleError("该帆布间没有现行刀片寿命卡，不能登记浸渍")
    if card.remaining_uses < 1:
        raise BladeRuleError(
            f"刀片寿命卡剩余刀次为 0，不能登记浸渍（批号 {card.blade_batch_no}，请更换新卡）"
        )
    dip = DipRun.objects.create(
        roll=roll,
        started_at=started_at,
        resin_pct=resin_pct,
        cure_hours=cure_hours,
        notes=notes,
    )
    card.remaining_uses -= 1
    card.save(update_fields=["remaining_uses"])
    if roll.status == ClothRoll.STATUS_RAW:
        roll.status = ClothRoll.STATUS_DIPPING
        roll.save(update_fields=["status", "updated_at"])
    return dip
