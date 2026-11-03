"""Seed rich ledger + support activity for samuelemeh266@gmail.com (investor + merchant)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from balances.models import BalanceTransaction
from balances.services import credit_available, debit_available, get_or_create_balance
from payments.models import PaymentIntent, PayoutMethod
from pools.models import Pool, PoolPosition, PoolWithdrawalRequest
from support.models import SupportMessage, SupportTicket

User = get_user_model()

EMAIL = "samuelemeh266@gmail.com"
PREFIX = "samuel-ops"


class Command(BaseCommand):
    help = (
        "Idempotently create investor/merchant ledger transactions and varied "
        f"support-ticket operations for {EMAIL}."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        user = User.objects.filter(email__iexact=EMAIL).select_related(
            "investor_profile",
            "merchant_profile",
        ).first()
        if not user:
            raise CommandError(f"User {EMAIL} not found.")
        if not hasattr(user, "investor_profile"):
            raise CommandError(f"{EMAIL} has no investor profile.")
        if not hasattr(user, "merchant_profile"):
            raise CommandError(f"{EMAIL} has no merchant profile.")

        admin = (
            User.objects.filter(is_admin=True).order_by("created_at").first()
            or User.objects.filter(is_staff=True).order_by("created_at").first()
        )
        if not admin:
            raise CommandError("Need at least one admin user to author support replies.")

        balance = get_or_create_balance(user)
        pool = (
            Pool.objects.filter(type=Pool.Type.CENTRALIZED, status=Pool.Status.ACTIVE, closed=False)
            .order_by("created_at")
            .first()
        )
        if pool is None:
            raise CommandError("No active centralized pool found.")

        PoolPosition.objects.update_or_create(
            pool=pool,
            investor=user.investor_profile,
            defaults={"principal_cents": max(1_050_000, 2_500_000)},
        )

        payout, _ = PayoutMethod.objects.get_or_create(
            user=user,
            label="Samuel ops · GTBank",
            defaults={"account_ref": "0123456789", "is_default": True},
        )

        # Ensure headroom for debit operations.
        self._credit(
            user,
            5_000_000,
            BalanceTransaction.Type.DEPOSIT,
            now - timedelta(days=55),
            "Ops seed wallet top-up",
            "topup",
            pool=None,
        )

        tx_keys = []
        tx_keys += self._seed_investor_ledger(user, pool, payout, now)
        tx_keys += self._seed_merchant_ledger(user, pool, payout, now)
        ticket_codes = self._seed_support_tickets(user, admin, now)

        balance.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f"Samuel ops seed complete for {EMAIL}"))
        self.stdout.write(f"  Ledger keys touched: {len(tx_keys)}")
        self.stdout.write(f"  Support tickets: {', '.join(ticket_codes)}")
        self.stdout.write(f"  Available balance now: {balance.available_cents} cents")

    def _seed_investor_ledger(self, user, pool, payout, now):
        keys = []
        # Successful deposits over time
        for i, (days, amount, label) in enumerate(
            [
                (48, 750_000, "Investor deposit · bank transfer"),
                (40, 400_000, "Investor deposit · card"),
                (22, 250_000, "Investor deposit · top-up"),
            ],
            start=1,
        ):
            keys.append(
                self._deposit_intent(
                    user,
                    amount,
                    now - timedelta(days=days),
                    f"inv-dep-{i}",
                    label,
                    pool=pool,
                )
            )

        # Allocations into pool
        for i, (days, amount) in enumerate([(38, 500_000), (20, 300_000)], start=1):
            keys.append(
                self._debit(
                    user,
                    amount,
                    BalanceTransaction.Type.POOL_ALLOCATE,
                    now - timedelta(days=days),
                    f"Allocated to {pool.name}",
                    f"inv-alloc-{i}",
                    pool=pool,
                )
            )

        # Returns + fees
        for i, (days, amount, label) in enumerate(
            [
                (14, 45_000, "Epoch return · week 1"),
                (7, 62_000, "Epoch return · week 2"),
                (2, 38_000, "Epoch return · week 3"),
            ],
            start=1,
        ):
            keys.append(
                self._credit(
                    user,
                    amount,
                    BalanceTransaction.Type.RETURN,
                    now - timedelta(days=days),
                    label,
                    f"inv-return-{i}",
                    pool=pool,
                )
            )
        keys.append(
            self._debit(
                user,
                12_000,
                BalanceTransaction.Type.FEE,
                now - timedelta(days=6),
                "Platform fee · investor",
                "inv-fee-1",
                pool=pool,
            )
        )

        # Successful wallet withdrawal
        keys.append(
            self._withdraw_intent(
                user,
                180_000,
                now - timedelta(days=10),
                "inv-wd-ok",
                payout,
                successful=True,
                label="Investor withdrawal · approved",
            )
        )
        # Pending admin-review withdrawal (intent only + pending tx)
        keys.append(
            self._withdraw_pending(
                user,
                95_000,
                now - timedelta(days=1),
                "inv-wd-pending",
                payout,
                "Investor withdrawal · awaiting review",
            )
        )
        # Rejected withdrawal intent + rejected ledger row
        keys.append(
            self._withdraw_rejected(
                user,
                50_000,
                now - timedelta(days=12),
                "inv-wd-rej",
                payout,
                "Investor withdrawal · rejected",
            )
        )

        # Pool withdraw request + successful pool_withdraw ledger
        PoolWithdrawalRequest.objects.get_or_create(
            pool=pool,
            investor=user.investor_profile,
            status=PoolWithdrawalRequest.Status.PENDING,
            defaults={
                "amount_cents": 160_000,
                "pool_share_bps_snapshot": 2200,
            },
        )
        keys.append(
            self._debit(
                user,
                75_000,
                BalanceTransaction.Type.POOL_WITHDRAW,
                now - timedelta(days=18),
                f"Pool redemption · {pool.name}",
                "inv-pool-wd-1",
                pool=pool,
            )
        )

        # Pending return (not yet posted to available)
        keys.append(
            self._pending_tx(
                user,
                55_000,
                BalanceTransaction.Type.RETURN,
                "Return pending epoch close",
                "inv-return-pending",
                pool=pool,
            )
        )
        return keys

    def _seed_merchant_ledger(self, user, pool, payout, now):
        keys = []
        for i, (days, amount, label) in enumerate(
            [
                (50, 900_000, "Merchant deposit · settlement float"),
                (28, 350_000, "Merchant deposit · repayment float"),
            ],
            start=1,
        ):
            keys.append(
                self._deposit_intent(
                    user,
                    amount,
                    now - timedelta(days=days),
                    f"mer-dep-{i}",
                    label,
                    pool=None,
                )
            )

        for i, (days, amount, label) in enumerate(
            [
                (25, 420_000, "Invoice funding received"),
                (15, 310_000, "Invoice funding received · batch 2"),
                (8, 275_000, "Invoice funding received · batch 3"),
            ],
            start=1,
        ):
            keys.append(
                self._credit(
                    user,
                    amount,
                    BalanceTransaction.Type.FUNDING,
                    now - timedelta(days=days),
                    label,
                    f"mer-fund-{i}",
                    pool=pool,
                )
            )

        for i, (days, amount, label) in enumerate(
            [
                (12, 150_000, "Invoice repayment"),
                (5, 220_000, "Invoice repayment · partial"),
            ],
            start=1,
        ):
            keys.append(
                self._debit(
                    user,
                    amount,
                    BalanceTransaction.Type.REPAYMENT,
                    now - timedelta(days=days),
                    label,
                    f"mer-repay-{i}",
                    pool=pool,
                )
            )

        keys.append(
            self._debit(
                user,
                18_000,
                BalanceTransaction.Type.FEE,
                now - timedelta(days=4),
                "Platform fee · merchant",
                "mer-fee-1",
                pool=pool,
            )
        )
        keys.append(
            self._withdraw_intent(
                user,
                260_000,
                now - timedelta(days=9),
                "mer-wd-ok",
                payout,
                successful=True,
                label="Merchant withdrawal · funded advance",
            )
        )
        keys.append(
            self._withdraw_pending(
                user,
                120_000,
                now - timedelta(hours=18),
                "mer-wd-pending",
                payout,
                "Merchant withdrawal · awaiting review",
            )
        )
        keys.append(
            self._withdraw_rejected(
                user,
                80_000,
                now - timedelta(days=16),
                "mer-wd-rej",
                payout,
                "Merchant withdrawal · rejected",
            )
        )
        return keys

    def _seed_support_tickets(self, user, admin, now):
        codes = []

        # Investor: active thread with admin reply
        t1 = self._ticket(
            user,
            "investor",
            "TK-SAM-INV-01",
            "Epoch return looks delayed",
            "returns",
            SupportTicket.Status.ACTIVE,
            now - timedelta(days=6),
        )
        self._msg(t1, user, "My weekly return for West Africa has not posted yet.", now - timedelta(days=6))
        self._msg(t1, admin, "Checking the epoch distribution queue — we will update shortly.", now - timedelta(days=5, hours=20))
        self._msg(t1, user, "Thanks — still waiting on the $620 credit.", now - timedelta(days=4))
        codes.append(t1.code)

        # Investor: pending (awaiting user)
        t2 = self._ticket(
            user,
            "investor",
            "TK-SAM-INV-02",
            "Need help verifying withdrawal bank",
            "withdrawals",
            SupportTicket.Status.PENDING,
            now - timedelta(days=3),
        )
        self._msg(t2, user, "I updated my payout method but withdrawals still fail KYC check.", now - timedelta(days=3))
        self._msg(
            t2,
            admin,
            "Please reply with a clear photo of the account name matching your profile.",
            now - timedelta(days=2, hours=12),
        )
        codes.append(t2.code)

        # Investor: closed after resolution
        t3 = self._ticket(
            user,
            "investor",
            "TK-SAM-INV-03",
            "Pool share percentage question",
            "pools",
            SupportTicket.Status.CLOSED,
            now - timedelta(days=20),
            closed_at=now - timedelta(days=17),
        )
        self._msg(t3, user, "How is pool share calculated after a mid-epoch deposit?", now - timedelta(days=20))
        self._msg(t3, admin, "Share is principal / total pool principal at the last snapshot.", now - timedelta(days=19))
        self._msg(t3, user, "Clear — closing this out.", now - timedelta(days=17, hours=2))
        codes.append(t3.code)

        # Merchant: active funding issue
        t4 = self._ticket(
            user,
            "merchant",
            "TK-SAM-MER-01",
            "Funding ready but withdraw button disabled",
            "funding",
            SupportTicket.Status.ACTIVE,
            now - timedelta(days=5),
        )
        self._msg(t4, user, "Invoice AS funded shows ready_to_withdraw but CTA is greyed out.", now - timedelta(days=5))
        self._msg(t4, admin, "Confirm a default payout method is set, then refresh the invoice page.", now - timedelta(days=4, hours=8))
        self._msg(t4, user, "Payout method added — still disabled on mobile.", now - timedelta(days=3))
        codes.append(t4.code)

        # Merchant: pending docs
        t5 = self._ticket(
            user,
            "merchant",
            "TK-SAM-MER-02",
            "Co-signer invite bounced",
            "cosign",
            SupportTicket.Status.PENDING,
            now - timedelta(days=2),
        )
        self._msg(t5, user, "Invite to co-signer bounced. Can you resend with a corrected email?", now - timedelta(days=2))
        self._msg(t5, admin, "Send the corrected email address and we will re-issue the invite.", now - timedelta(days=1, hours=6))
        codes.append(t5.code)

        # Merchant: closed then reopened by admin (status active, closed_at cleared)
        t6 = self._ticket(
            user,
            "merchant",
            "TK-SAM-MER-03",
            "Late fee dispute on repaid invoice",
            "repayment",
            SupportTicket.Status.ACTIVE,
            now - timedelta(days=30),
            closed_at=None,
        )
        self._msg(t6, user, "I was charged a late fee after full repayment posted.", now - timedelta(days=30))
        self._msg(t6, admin, "Fee reversed — closing ticket.", now - timedelta(days=28))
        # Simulate close then reopen
        t6.status = SupportTicket.Status.CLOSED
        t6.closed_at = now - timedelta(days=27)
        t6.save(update_fields=["status", "closed_at", "updated_at"])
        t6.status = SupportTicket.Status.ACTIVE
        t6.closed_at = None
        t6.last_message_at = now - timedelta(days=1)
        t6.save(update_fields=["status", "closed_at", "last_message_at", "updated_at"])
        self._msg(t6, admin, "Reopening — accounting flagged a second fee line. Investigating.", now - timedelta(days=1))
        self._msg(t6, user, "Appreciate the reopen. Please confirm when the second fee is cleared.", now - timedelta(hours=10))
        codes.append(t6.code)

        # Merchant: closed without reopen
        t7 = self._ticket(
            user,
            "merchant",
            "TK-SAM-MER-04",
            "How to download funded invoice PDF",
            "documents",
            SupportTicket.Status.CLOSED,
            now - timedelta(days=12),
            closed_at=now - timedelta(days=11),
        )
        self._msg(t7, user, "Where do I download the financed invoice packet?", now - timedelta(days=12))
        self._msg(t7, admin, "Open the invoice → Documents → View. Closing as resolved.", now - timedelta(days=11, hours=4))
        codes.append(t7.code)

        return codes

    # ── support helpers ──────────────────────────────────────────────

    def _ticket(self, user, role_scope, code, title, topic, status, created_at, closed_at=None):
        ticket, _ = SupportTicket.objects.update_or_create(
            code=code,
            defaults={
                "requester": user,
                "role_scope": role_scope,
                "title": title,
                "topic": topic,
                "status": status,
                "closed_at": closed_at,
                "last_message_at": created_at,
            },
        )
        SupportTicket.objects.filter(pk=ticket.pk).update(
            created_at=created_at,
            updated_at=created_at,
            last_message_at=created_at,
        )
        return SupportTicket.objects.get(pk=ticket.pk)

    def _msg(self, ticket, author, body, when):
        existing = SupportMessage.objects.filter(ticket=ticket, author=author, body=body).first()
        if existing:
            SupportMessage.objects.filter(pk=existing.pk).update(created_at=when, updated_at=when)
            return existing
        msg = SupportMessage.objects.create(ticket=ticket, author=author, body=body)
        SupportMessage.objects.filter(pk=msg.pk).update(created_at=when, updated_at=when)
        ticket.last_message_at = when
        ticket.save(update_fields=["last_message_at", "updated_at"])
        return msg

    # ── ledger helpers ───────────────────────────────────────────────

    def _key(self, suffix: str) -> str:
        return f"{PREFIX}-{suffix}"

    def _stamp(self, model, pk, when):
        model.objects.filter(pk=pk).update(created_at=when, updated_at=when)

    def _credit(self, user, amount, tx_type, when, label, key, *, pool=None, invoice=None):
        tx = credit_available(
            user,
            amount,
            tx_type=tx_type,
            destination_label=label,
            pool=pool,
            invoice=invoice,
            idempotency_key=self._key(f"tx-{key}"),
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        return key

    def _debit(self, user, amount, tx_type, when, label, key, *, pool=None, invoice=None):
        tx = debit_available(
            user,
            amount,
            tx_type=tx_type,
            destination_label=label,
            pool=pool,
            invoice=invoice,
            idempotency_key=self._key(f"tx-{key}"),
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        return key

    def _pending_tx(self, user, amount, tx_type, label, key, *, pool=None):
        balance = get_or_create_balance(user)
        tx, _ = BalanceTransaction.objects.get_or_create(
            idempotency_key=self._key(f"tx-{key}"),
            defaults={
                "balance": balance,
                "type": tx_type,
                "status": BalanceTransaction.Status.PENDING,
                "amount_cents": amount,
                "destination_label": label,
                "pool": pool,
            },
        )
        return key

    def _deposit_intent(self, user, amount, when, key, label, *, pool=None):
        intent, _ = PaymentIntent.objects.get_or_create(
            idempotency_key=self._key(f"intent-{key}"),
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.DEPOSIT,
                "amount_cents": amount,
                "status": PaymentIntent.Status.SUCCESSFUL,
                "processor": "dummy",
                "processor_ref": key,
                "settled_at": when,
            },
        )
        self._stamp(PaymentIntent, intent.pk, when)
        tx = credit_available(
            user,
            amount,
            tx_type=BalanceTransaction.Type.DEPOSIT,
            destination_label=label,
            pool=pool,
            payment_intent=intent,
            idempotency_key=self._key(f"tx-{key}"),
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        return key

    def _withdraw_intent(self, user, amount, when, key, payout, *, successful, label):
        intent, _ = PaymentIntent.objects.get_or_create(
            idempotency_key=self._key(f"intent-{key}"),
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.WITHDRAWAL,
                "amount_cents": amount,
                "status": PaymentIntent.Status.SUCCESSFUL
                if successful
                else PaymentIntent.Status.PENDING,
                "processor": "dummy",
                "processor_ref": key,
                "payout_method": payout,
                "settled_at": when if successful else None,
                "requires_admin_review": not successful,
                "admin_decision": PaymentIntent.AdminDecision.APPROVE if successful else "",
            },
        )
        self._stamp(PaymentIntent, intent.pk, when)
        if successful:
            tx = debit_available(
                user,
                amount,
                tx_type=BalanceTransaction.Type.WITHDRAWAL,
                destination_label=label,
                payment_intent=intent,
                idempotency_key=self._key(f"tx-{key}"),
            )
            self._stamp(BalanceTransaction, tx.pk, when)
        return key

    def _withdraw_pending(self, user, amount, when, key, payout, label):
        intent, _ = PaymentIntent.objects.get_or_create(
            idempotency_key=self._key(f"intent-{key}"),
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.WITHDRAWAL,
                "amount_cents": amount,
                "status": PaymentIntent.Status.PENDING,
                "processor": "dummy",
                "processor_ref": key,
                "payout_method": payout,
                "requires_admin_review": True,
            },
        )
        self._stamp(PaymentIntent, intent.pk, when)
        balance = get_or_create_balance(user)
        tx, _ = BalanceTransaction.objects.get_or_create(
            idempotency_key=self._key(f"tx-{key}"),
            defaults={
                "balance": balance,
                "type": BalanceTransaction.Type.WITHDRAWAL,
                "status": BalanceTransaction.Status.PENDING,
                "amount_cents": amount,
                "destination_label": label,
                "payment_intent": intent,
            },
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        return key

    def _withdraw_rejected(self, user, amount, when, key, payout, label):
        intent, _ = PaymentIntent.objects.get_or_create(
            idempotency_key=self._key(f"intent-{key}"),
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.WITHDRAWAL,
                "amount_cents": amount,
                "status": PaymentIntent.Status.REJECTED,
                "processor": "dummy",
                "processor_ref": key,
                "payout_method": payout,
                "requires_admin_review": True,
                "admin_decision": PaymentIntent.AdminDecision.REJECT,
                "settled_at": when,
            },
        )
        self._stamp(PaymentIntent, intent.pk, when)
        balance = get_or_create_balance(user)
        tx, _ = BalanceTransaction.objects.get_or_create(
            idempotency_key=self._key(f"tx-{key}"),
            defaults={
                "balance": balance,
                "type": BalanceTransaction.Type.WITHDRAWAL,
                "status": BalanceTransaction.Status.REJECTED,
                "amount_cents": amount,
                "destination_label": label,
                "payment_intent": intent,
            },
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        return key
