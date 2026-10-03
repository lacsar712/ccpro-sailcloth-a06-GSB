"""刀片寿命卡与浸渍登记规则测试。

竞态用例需要支持行锁的数据库（PostgreSQL），
通过 TransactionTestCase + 双线程模拟两名浸胶工同时登记。
"""

import json
import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from .models import BladeCard, ClothRoll, DipRun, Loft

User = get_user_model()


def bearer(user) -> str:
    return f"Bearer {str(RefreshToken.for_user(user).access_token)}"


def post_dip(client, roll_id, token, **over):
    payload = {
        "rollId": roll_id,
        "startedAt": timezone.now().isoformat(),
        "resinPct": "28.00",
        "cureHours": None,
        "notes": "",
    }
    payload.update(over)
    return client.post(
        "/api/dips/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=token,
    )


class BladeCardApiTests(TestCase):
    """刀片寿命卡 CRUD / 权限 / 顺序扣减。"""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="x", role=User.ROLE_ADMIN, is_superuser=True
        )
        self.worker = User.objects.create_user(
            username="worker", password="x", role=User.ROLE_WORKER
        )
        self.loft = Loft.objects.create(name="北岸帆布间")
        self.roll_a = ClothRoll.objects.create(loft=self.loft, roll_code="R-01")
        self.roll_b = ClothRoll.objects.create(loft=self.loft, roll_code="R-02")
        self.card = BladeCard.objects.create(
            loft=self.loft, blade_batch_no="BLADE-1", remaining_uses=1
        )
        self.client = Client()
        self.admin_auth = bearer(self.admin)
        self.worker_auth = bearer(self.worker)

    def test_worker_can_create_card(self):
        other = Loft.objects.create(name="南岸帆布间")
        resp = self.client.post(
            "/api/bladecards/",
            data=json.dumps(
                {"loftId": other.id, "bladeBatchNo": "B-9", "remainingUses": 3}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(BladeCard.objects.filter(loft=other).count(), 1)

    def test_second_active_card_rejected(self):
        resp = self.client.post(
            "/api/bladecards/",
            data=json.dumps(
                {"loftId": self.loft.id, "bladeBatchNo": "B-2", "remainingUses": 5}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("现行", resp.content.decode())

    def test_negative_remaining_rejected(self):
        other = Loft.objects.create(name="南岸帆布间")
        resp = self.client.post(
            "/api/bladecards/",
            data=json.dumps(
                {"loftId": other.id, "bladeBatchNo": "B-3", "remainingUses": -1}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_void_requires_admin(self):
        resp = self.client.post(
            f"/api/bladecards/{self.card.id}/void/",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 403)
        self.card.refresh_from_db()
        self.assertIsNone(self.card.voided_at)

        resp = self.client.post(
            f"/api/bladecards/{self.card.id}/void/",
            HTTP_AUTHORIZATION=self.admin_auth,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.card.refresh_from_db()
        self.assertIsNotNone(self.card.voided_at)

    def test_voided_card_uses_unavailable(self):
        self.card.remaining_uses = 5
        self.card.voided_at = timezone.now()
        self.card.save()
        resp = post_dip(self.client, self.roll_a.id, self.worker_auth)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("没有现行刀片寿命卡", resp.content.decode())
        self.assertEqual(DipRun.objects.count(), 0)

    def test_successful_dip_decrements_and_flips_roll(self):
        resp = post_dip(self.client, self.roll_a.id, self.worker_auth)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.card.refresh_from_db()
        self.roll_a.refresh_from_db()
        self.assertEqual(self.card.remaining_uses, 0)
        self.assertEqual(self.roll_a.status, ClothRoll.STATUS_DIPPING)
        self.assertEqual(DipRun.objects.count(), 1)

    def test_exhausted_card_blocks_registration(self):
        resp = post_dip(self.client, self.roll_a.id, self.worker_auth)
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = post_dip(self.client, self.roll_b.id, self.worker_auth)
        self.assertEqual(resp.status_code, 400)
        body = resp.content.decode()
        self.assertIn("剩余刀次为 0", body)
        self.assertEqual(DipRun.objects.count(), 1)
        self.roll_b.refresh_from_db()
        self.assertEqual(self.roll_b.status, ClothRoll.STATUS_RAW)

    def test_missing_card_blocks_registration(self):
        other = Loft.objects.create(name="无卡间")
        roll = ClothRoll.objects.create(loft=other, roll_code="R-09")
        resp = post_dip(self.client, roll.id, self.worker_auth)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("没有现行刀片寿命卡", resp.content.decode())

    def test_cured_rule_keeps_twelve_hour_bar(self):
        """刀次规则不得掺进固化：时长满 12h 仍可标已固化，不满仍被挡。"""
        self.card.remaining_uses = 5
        self.card.save()
        resp = post_dip(
            self.client, self.roll_a.id, self.worker_auth, cureHours="14.50"
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client.patch(
            f"/api/rolls/{self.roll_a.id}/",
            data=json.dumps({"status": "cured"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        resp = post_dip(
            self.client, self.roll_b.id, self.worker_auth, cureHours="4.00"
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client.patch(
            f"/api/rolls/{self.roll_b.id}/",
            data=json.dumps({"status": "cured"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.worker_auth,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("12", resp.content.decode())


class BladeCardRaceTests(TransactionTestCase):
    """两名浸胶工抢同间两卷、仅剩 1 刀次：只许一笔入库并扣完。"""

    def setUp(self):
        self.worker1 = User.objects.create_user(
            username="dipping-1", password="x", role=User.ROLE_WORKER
        )
        self.worker2 = User.objects.create_user(
            username="dipping-2", password="x", role=User.ROLE_WORKER
        )
        self.loft = Loft.objects.create(name="北岸帆布间")
        self.roll_a = ClothRoll.objects.create(loft=self.loft, roll_code="R-01")
        self.roll_b = ClothRoll.objects.create(loft=self.loft, roll_code="R-02")
        self.card = BladeCard.objects.create(
            loft=self.loft, blade_batch_no="BLADE-1", remaining_uses=1
        )

    def test_concurrent_dips_only_one_lands(self):
        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(idx, roll_id, token):
            try:
                client = Client()
                barrier.wait(timeout=15)
                resp = post_dip(client, roll_id, token)
                results[idx] = (resp.status_code, resp.content.decode())
            finally:
                connections.close_all()

        t1 = threading.Thread(
            target=worker, args=(0, self.roll_a.id, bearer(self.worker1))
        )
        t2 = threading.Thread(
            target=worker, args=(1, self.roll_b.id, bearer(self.worker2))
        )
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        self.assertIsNotNone(results[0], "线程 1 未在限时内返回")
        self.assertIsNotNone(results[1], "线程 2 未在限时内返回")

        statuses = sorted(r[0] for r in results)
        self.assertEqual(
            statuses, [201, 400], f"两笔登记应一笔成功一笔被挡，实际：{results}"
        )
        loser_body = next(body for code, body in results if code == 400)
        self.assertIn("剩余刀次为 0", loser_body)

        self.card.refresh_from_db()
        self.assertEqual(self.card.remaining_uses, 0, "剩余刀次应恰好扣到 0")
        self.assertEqual(DipRun.objects.count(), 1, "只许一笔浸渍入库")

        self.roll_a.refresh_from_db()
        self.roll_b.refresh_from_db()
        statuses_by_roll = {self.roll_a.status, self.roll_b.status}
        self.assertEqual(
            statuses_by_roll,
            {ClothRoll.STATUS_DIPPING, ClothRoll.STATUS_RAW},
            "入库那卷应转浸渍中，被挡那卷仍是原布",
        )
