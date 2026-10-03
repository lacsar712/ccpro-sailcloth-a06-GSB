import threading
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from .models import BladeCard, ClothRoll, DipRun, Loft

User = get_user_model()

DIP_URL = "/api/dips/"
CARD_URL = "/api/bladecards/"


def make_user(username, role):
    return User.objects.create_user(username=username, password="pw123456", role=role)


def dip_payload(roll, **overrides):
    data = {
        "rollId": roll.id,
        "startedAt": timezone.now().isoformat(),
        "resinPct": "28.00",
        "cureHours": None,
        "notes": "",
    }
    data.update(overrides)
    return data


class BladeCardApiTests(APITestCase):
    def setUp(self):
        self.admin = make_user("admin", User.ROLE_ADMIN)
        self.worker = make_user("worker", User.ROLE_WORKER)
        self.loft = Loft.objects.create(name="北岸帆布间")
        self.roll1 = ClothRoll.objects.create(loft=self.loft, roll_code="R-01")
        self.roll2 = ClothRoll.objects.create(loft=self.loft, roll_code="R-02")

    def card_payload(self, **overrides):
        data = {"loftId": self.loft.id, "bladeBatch": "BL-001", "remainingUses": 3}
        data.update(overrides)
        return data

    # ---- 建卡 ----

    def test_worker_can_create_card(self):
        self.client.force_authenticate(self.worker)
        resp = self.client.post(CARD_URL, self.card_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        card = BladeCard.objects.get()
        self.assertEqual(card.remaining_uses, 3)
        self.assertIsNone(card.voided_at)

    def test_negative_remaining_rejected(self):
        self.client.force_authenticate(self.worker)
        resp = self.client.post(
            CARD_URL, self.card_payload(remainingUses=-1), format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BladeCard.objects.count(), 0)

    def test_second_active_card_same_loft_rejected(self):
        BladeCard.objects.create(
            loft=self.loft, blade_batch="BL-001", remaining_uses=2
        )
        self.client.force_authenticate(self.worker)
        resp = self.client.post(
            CARD_URL, self.card_payload(bladeBatch="BL-002"), format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(BladeCard.objects.count(), 1)

    def test_second_card_allowed_after_void(self):
        card = BladeCard.objects.create(
            loft=self.loft, blade_batch="BL-001", remaining_uses=2,
            voided_at=timezone.now(),
        )
        self.client.force_authenticate(self.worker)
        resp = self.client.post(
            CARD_URL, self.card_payload(bladeBatch="BL-002"), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            BladeCard.objects.filter(loft=self.loft, voided_at__isnull=True).count(), 1
        )
        card.refresh_from_db()
        self.assertIsNotNone(card.voided_at)

    # ---- 作废权限 ----

    def test_void_requires_admin(self):
        card = BladeCard.objects.create(
            loft=self.loft, blade_batch="BL-001", remaining_uses=2
        )
        self.client.force_authenticate(self.worker)
        resp = self.client.post(f"{CARD_URL}{card.id}/void/")
        self.assertEqual(resp.status_code, 403)
        card.refresh_from_db()
        self.assertIsNone(card.voided_at)

        self.client.force_authenticate(self.admin)
        resp = self.client.post(f"{CARD_URL}{card.id}/void/")
        self.assertEqual(resp.status_code, 200, resp.data)
        card.refresh_from_db()
        self.assertIsNotNone(card.voided_at)

    # ---- 登记浸渍扣刀次 ----

    def test_dip_consumes_use_and_marks_dipping(self):
        BladeCard.objects.create(loft=self.loft, blade_batch="BL-001", remaining_uses=1)
        self.client.force_authenticate(self.worker)
        resp = self.client.post(DIP_URL, dip_payload(self.roll1), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)

        card = BladeCard.objects.get()
        self.assertEqual(card.remaining_uses, 0)
        self.roll1.refresh_from_db()
        self.assertEqual(self.roll1.status, ClothRoll.STATUS_DIPPING)
        self.assertEqual(DipRun.objects.filter(roll=self.roll1).count(), 1)

    def test_dip_blocked_when_no_uses_left(self):
        BladeCard.objects.create(loft=self.loft, blade_batch="BL-001", remaining_uses=0)
        self.client.force_authenticate(self.worker)
        resp = self.client.post(DIP_URL, dip_payload(self.roll1), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("刀次", resp.data["detail"])

        # 事务整体回滚：无浸渍记录、布卷仍是原布、刀次不变
        self.assertEqual(DipRun.objects.count(), 0)
        self.roll1.refresh_from_db()
        self.assertEqual(self.roll1.status, ClothRoll.STATUS_RAW)
        self.assertEqual(BladeCard.objects.get().remaining_uses, 0)

    def test_dip_blocked_without_card(self):
        self.client.force_authenticate(self.worker)
        resp = self.client.post(DIP_URL, dip_payload(self.roll1), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("没有现行刀片寿命卡", resp.data["detail"])
        self.assertEqual(DipRun.objects.count(), 0)

    def test_dip_blocked_after_card_voided(self):
        card = BladeCard.objects.create(
            loft=self.loft, blade_batch="BL-001", remaining_uses=5
        )
        card.voided_at = timezone.now()
        card.save(update_fields=["voided_at"])
        self.client.force_authenticate(self.worker)
        resp = self.client.post(DIP_URL, dip_payload(self.roll1), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DipRun.objects.count(), 0)

    # ---- 固化规则不受刀次影响 ----

    def test_cured_rule_not_affected_by_blade(self):
        # 刀次已用完，但标「已固化」只看最近浸渍时长是否满 12 小时
        BladeCard.objects.create(loft=self.loft, blade_batch="BL-001", remaining_uses=0)
        DipRun.objects.create(
            roll=self.roll1,
            started_at=timezone.now(),
            resin_pct="28.00",
            cure_hours="13.00",
        )
        self.client.force_authenticate(self.worker)
        resp = self.client.patch(
            f"/api/rolls/{self.roll1.id}/", {"status": "cured"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.roll1.refresh_from_db()
        self.assertEqual(self.roll1.status, ClothRoll.STATUS_CURED)

        # 时长不足 12 小时仍然挡住
        roll2 = self.roll2
        DipRun.objects.create(
            roll=roll2,
            started_at=timezone.now(),
            resin_pct="26.00",
            cure_hours="4.00",
        )
        resp = self.client.patch(
            f"/api/rolls/{roll2.id}/", {"status": "cured"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    # ---- 列表过滤 ----

    def test_state_filter(self):
        BladeCard.objects.create(loft=self.loft, blade_batch="BL-001", remaining_uses=1)
        other_loft = Loft.objects.create(name="南岸帆布间")
        BladeCard.objects.create(
            loft=other_loft, blade_batch="BL-002", remaining_uses=0,
            voided_at=timezone.now(),
        )
        self.client.force_authenticate(self.worker)
        active = self.client.get(CARD_URL, {"state": "active"}).data["results"]
        voided = self.client.get(CARD_URL, {"state": "voided"}).data["results"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["bladeBatch"], "BL-001")
        self.assertEqual(len(voided), 1)
        self.assertEqual(voided[0]["bladeBatch"], "BL-002")


class BladeConcurrencyTests(TransactionTestCase):
    """两名浸胶工同时给同间两卷各登一笔、仅剩 1 刀次：只许一笔入库并扣完。"""

    def setUp(self):
        self.loft = Loft.objects.create(name="北岸帆布间")
        self.roll1 = ClothRoll.objects.create(loft=self.loft, roll_code="R-01")
        self.roll2 = ClothRoll.objects.create(loft=self.loft, roll_code="R-02")
        self.card = BladeCard.objects.create(
            loft=self.loft, blade_batch="BL-001", remaining_uses=1
        )
        self.user1 = make_user("worker1", User.ROLE_WORKER)
        self.user2 = make_user("worker2", User.ROLE_WORKER)

    @skipUnless(connection.vendor == "postgresql", "行锁并发测试需要 PostgreSQL")
    def test_only_one_dip_wins_when_one_use_left(self):
        results = {}
        barrier = threading.Barrier(2)

        def register(key, user, roll):
            client = APIClient()
            client.force_authenticate(user)
            try:
                barrier.wait(timeout=15)
                resp = client.post(DIP_URL, dip_payload(roll), format="json")
                results[key] = resp.status_code
            finally:
                connection.close()

        threads = [
            threading.Thread(target=register, args=("a", self.user1, self.roll1)),
            threading.Thread(target=register, args=("b", self.user2, self.roll2)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            self.assertFalse(t.is_alive(), "登记线程超时未结束")

        # 恰一笔 201、一笔 400
        self.assertEqual(sorted(results.values()), [201, 400], results)

        # 刀次恰好扣一次到 0，浸渍记录恰一条
        self.card.refresh_from_db()
        self.assertEqual(self.card.remaining_uses, 0)
        self.assertEqual(DipRun.objects.count(), 1)

        # 恰一卷变浸渍中，另一卷仍是原布
        self.roll1.refresh_from_db()
        self.roll2.refresh_from_db()
        statuses = sorted([self.roll1.status, self.roll2.status])
        self.assertEqual(
            statuses, [ClothRoll.STATUS_DIPPING, ClothRoll.STATUS_RAW]
        )
        dipped_roll = DipRun.objects.get().roll
        self.assertEqual(dipped_roll.status, ClothRoll.STATUS_DIPPING)
