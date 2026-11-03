"""Seed pools, invoices, and ledger activity for all email-verified users."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import InvestorProfile, MerchantProfile
from balances.models import BalanceTransaction
from balances.services import credit_available, debit_available, get_or_create_balance
from epochs.models import Epoch
from invoices.models import Invoice, InvoiceAcknowledgement, InvoiceDocument
from payments.models import PaymentIntent, PayoutMethod
from pools.models import Pool, PoolLoanTier, PoolPosition, PoolWithdrawalRequest

User = get_user_model()

PREFIX = "activity-seed"
ACTIVITY_POOL_NAME = "Activity Seed Central Pool"


@dataclass
class SeedStats:
    investors: int = 0
    merchants: int = 0
    balances: int = 0
    positions_created: int = 0
    positions_updated: int = 0
    withdrawal_requests_created: int = 0
    invoices_created: int = 0
    invoices_updated: int = 0
    payout_methods_created: int = 0
    ledger_tx: int = 0
    pool_created: bool = False
    tier_created: bool = False
    epoch_created: bool = False
    notes: list[str] = field(default_factory=list)

    def bump_ledger(self, n: int = 1) -> None:
        self.ledger_tx += n


class Command(BaseCommand):
    help = (
        "Idempotently seed pool positions, invoices, and balance activity "
        "for every user with email_verified=True."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        stats = SeedStats()

        verified = User.objects.filter(email_verified=True).order_by("email")
        investor_profiles = list(
            InvestorProfile.objects.filter(user__email_verified=True)
            .select_related("user")
            .order_by("user__email")
        )
        merchant_profiles = list(
            MerchantProfile.objects.filter(user__email_verified=True)
            .select_related("user")
            .order_by("user__email")
        )

        if not verified.exists():
            self.stdout.write(self.style.WARNING("No email-verified users found; nothing to seed."))
            return

        admin_user = (
            verified.filter(is_admin=True).first()
            or verified.filter(is_staff=True).first()
            or verified.first()
        )
        pool_owner = investor_profiles[0] if investor_profiles else None

        central, tier = self._ensure_central_pool(admin_user, pool_owner, now, stats)
        if central is None:
            self.stdout.write(
                self.style.WARNING(
                    "No investor profiles among verified users; skipping pool/investor ledger seeding."
                )
            )
        else:
            for profile in investor_profiles:
                self._seed_investor(profile, central, now, stats)

        for profile in merchant_profiles:
            self._seed_merchant(profile, central, tier, now, stats)

        for user in verified:
            get_or_create_balance(user)
            stats.balances += 1

        self._print_summary(stats, len(investor_profiles), len(merchant_profiles))

    def _print_summary(self, stats: SeedStats, investor_count: int, merchant_count: int) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Activity seed complete (idempotent; safe to re-run)."))
        self.stdout.write(f"  Verified investors processed: {investor_count}")
        self.stdout.write(f"  Verified merchants processed: {merchant_count}")
        self.stdout.write(f"  Pool positions created/updated: {stats.positions_created}/{stats.positions_updated}")
        self.stdout.write(f"  Invoices created/updated: {stats.invoices_created}/{stats.invoices_updated}")
        self.stdout.write(f"  Pending pool withdrawal requests (new): {stats.withdrawal_requests_created}")
        self.stdout.write(f"  Payout methods (new): {stats.payout_methods_created}")
        self.stdout.write(f"  Ledger movements touched: {stats.ledger_tx}")
        if stats.pool_created:
            self.stdout.write(f"  Created shared pool: {ACTIVITY_POOL_NAME}")
        if stats.tier_created:
            self.stdout.write("  Created default 30-day loan tier on shared pool")
        if stats.epoch_created:
            self.stdout.write("  Created funding-open epoch on shared pool")
        for note in stats.notes:
            self.stdout.write(f"  Note: {note}")

    def _ensure_central_pool(self, admin_user, pool_owner, now, stats: SeedStats):
        central = (
            Pool.objects.filter(
                type=Pool.Type.CENTRALIZED,
                status=Pool.Status.ACTIVE,
                closed=False,
            )
            .order_by("created_at")
            .first()
        )
        if central is None:
            if pool_owner is None:
                return None, None
            central, created = Pool.objects.get_or_create(
                name=ACTIVITY_POOL_NAME,
                defaults={
                    "type": Pool.Type.CENTRALIZED,
                    "owner_investor": pool_owner,
                    "created_by": admin_user,
                },
            )
            if created:
                stats.pool_created = True
            central.type = Pool.Type.CENTRALIZED
            central.status = Pool.Status.ACTIVE
            central.closed = False
            central.owner_investor = pool_owner
            central.created_by = admin_user
            central.countries = ["Nigeria", "Ghana"]
            central.industries = ["Agriculture", "Manufacturing", "Trade"]
            central.strategy = "Shared receivables pool for activity seed data."
            central.min_deposit_cents = 100_000
            central.target_size_cents = 50_000_000
            central.exposure_limit_percent = 15
            central.auto_funding = True
            central.allow_public = True
            central.target_return_bps = 1800
            central.save()

        tier = PoolLoanTier.objects.filter(pool=central).order_by("interest_bps").first()
        if tier is None:
            tier, created = PoolLoanTier.objects.get_or_create(
                pool=central,
                name="30 day",
                defaults={
                    "duration_days": 30,
                    "interest_bps": 1200,
                    "invoice_min_cents": 100_000,
                    "invoice_max_cents": 5_000_000,
                },
            )
            if created:
                stats.tier_created = True

        if not Epoch.objects.filter(pool=central).exists():
            _, created = Epoch.objects.get_or_create(
                pool=central,
                index=1,
                defaults={
                    "starts_at": now - timedelta(days=10),
                    "ends_at": now + timedelta(days=20),
                    "state": Epoch.State.FUNDING_OPEN,
                },
            )
            if created:
                stats.epoch_created = True

        return central, tier

    def _seed_investor(self, profile: InvestorProfile, pool: Pool, now, stats: SeedStats):
        user = profile.user
        get_or_create_balance(user)
        stats.investors += 1
        slug = self._email_slug(user.email)
        amounts = self._amounts_for_email(user.email)

        position, created = PoolPosition.objects.update_or_create(
            pool=pool,
            investor=profile,
            defaults={"principal_cents": amounts["principal"]},
        )
        if created:
            stats.positions_created += 1
        else:
            stats.positions_updated += 1

        self._deposit(user, amounts["deposit"], now - timedelta(days=30), pool, f"{slug}-dep", stats)
        self._move(
            user,
            amounts["allocate"],
            BalanceTransaction.Type.POOL_ALLOCATE,
            now - timedelta(days=20),
            f"Allocated to {pool.name}",
            f"{slug}-alloc",
            pool=pool,
            debit=True,
            stats=stats,
        )
        self._move(
            user,
            amounts["return"],
            BalanceTransaction.Type.RETURN,
            now - timedelta(days=5),
            "Pool return",
            f"{slug}-return",
            pool=pool,
            stats=stats,
        )
        self._move(
            user,
            amounts["fee"],
            BalanceTransaction.Type.FEE,
            now - timedelta(days=4),
            "Platform fee",
            f"{slug}-fee",
            pool=pool,
            debit=True,
            stats=stats,
        )
        self._withdraw(user, amounts["withdraw"], now - timedelta(days=3), f"{slug}-wd", stats=stats)
        self._pending_return(user, amounts["return_pending"], pool, f"{slug}-return-pending", stats)

        _, wr_created = PoolWithdrawalRequest.objects.get_or_create(
            pool=pool,
            investor=profile,
            status=PoolWithdrawalRequest.Status.PENDING,
            defaults={
                "amount_cents": amounts["pool_withdraw"],
                "pool_share_bps_snapshot": amounts["share_bps"],
            },
        )
        if wr_created:
            stats.withdrawal_requests_created += 1

    def _seed_merchant(
        self,
        profile: MerchantProfile,
        pool: Pool | None,
        tier,
        now,
        stats: SeedStats,
    ):
        user = profile.user
        stats.merchants += 1
        slug = self._email_slug(user.email)
        industry = profile.industry or "General"
        years = profile.years_in_operation or 3
        buyer = profile.business_name or user.full_name or "Activity buyer"

        payout, payout_created = PayoutMethod.objects.get_or_create(
            user=user,
            label=f"Activity seed · {buyer[:40]}",
            defaults={"account_ref": f"ACT{slug[:8]}", "is_default": True},
        )
        if payout_created:
            stats.payout_methods_created += 1

        get_or_create_balance(user)
        self._deposit(user, 1_000_000, now - timedelta(days=60), None, f"{slug}-m-dep", stats)

        pending, c1 = self._invoice(
            profile,
            f"AS-{slug}-01",
            f"Activity seed · pending review ({slug})",
            buyer,
            800_000,
            650_000,
            30,
            now.date() + timedelta(days=35),
            tier if pool else None,
            pool,
            industry=industry,
            years=years,
            review=Invoice.ReviewStatus.PENDING_REVIEW,
            insurance=Invoice.InsuranceStatus.PENDING,
            step=Invoice.FinanceStep.CREATED,
            payout=Invoice.PayoutStatus.NONE,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.PENDING,
            outstanding=0,
            funded=0,
            left=650_000,
        )
        self._bump_invoice_stats(c1, stats)
        InvoiceDocument.objects.get_or_create(
            invoice=pending,
            name="Activity delivery note.pdf",
            defaults={"visibility": InvoiceDocument.Visibility.AVAILABLE},
        )

        funded, c2 = self._invoice(
            profile,
            f"AS-{slug}-02",
            f"Activity seed · funded ({slug})",
            buyer,
            1_100_000,
            900_000,
            30,
            now.date() + timedelta(days=28),
            tier if pool else None,
            pool,
            industry=industry,
            years=years,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_FUNDED,
            payout=Invoice.PayoutStatus.READY,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=954_000,
            funded=900_000,
            left=0,
            funded_at=now - timedelta(days=7),
            repayment_amount=954_000,
        )
        self._bump_invoice_stats(c2, stats)
        if funded.review_status == Invoice.ReviewStatus.APPROVED:
            for kind, _label in InvoiceAcknowledgement.Kind.choices:
                InvoiceAcknowledgement.objects.get_or_create(invoice=funded, kind=kind)
            InvoiceDocument.objects.get_or_create(
                invoice=funded,
                name="Activity contract.pdf",
                defaults={"visibility": InvoiceDocument.Visibility.AVAILABLE},
            )

        repaid, c3 = self._invoice(
            profile,
            f"AS-{slug}-03",
            f"Activity seed · repaid ({slug})",
            buyer,
            600_000,
            500_000,
            30,
            now.date() - timedelta(days=14),
            tier if pool else None,
            pool,
            industry=industry,
            years=years,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_REPAID,
            payout=Invoice.PayoutStatus.SETTLED,
            repayment=Invoice.RepaymentState.REPAID,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=0,
            funded=500_000,
            left=0,
            funded_at=now - timedelta(days=45),
            repayment_amount=530_000,
        )
        self._bump_invoice_stats(c3, stats)
        if repaid.review_status == Invoice.ReviewStatus.APPROVED:
            for kind, _label in InvoiceAcknowledgement.Kind.choices:
                InvoiceAcknowledgement.objects.get_or_create(invoice=repaid, kind=kind)

        if pool is not None:
            self._move(
                user,
                funded.funded_amount_cents,
                BalanceTransaction.Type.FUNDING,
                now - timedelta(days=7),
                f"Invoice funding {funded.code}",
                f"{slug}-fund-02",
                invoice=funded,
                pool=pool,
                stats=stats,
            )
            self._move(
                user,
                repaid.funded_amount_cents,
                BalanceTransaction.Type.FUNDING,
                now - timedelta(days=45),
                f"Invoice funding {repaid.code}",
                f"{slug}-fund-03",
                invoice=repaid,
                pool=pool,
                stats=stats,
            )
            self._withdraw(
                user,
                repaid.funded_amount_cents,
                now - timedelta(days=44),
                f"{slug}-wd-repaid",
                stats=stats,
                payout=payout,
            )
            self._move(
                user,
                repaid.repayment_amount_cents,
                BalanceTransaction.Type.REPAYMENT,
                now - timedelta(days=15),
                f"Repayment {repaid.code}",
                f"{slug}-repay-03",
                invoice=repaid,
                debit=True,
                stats=stats,
            )

    @staticmethod
    def _bump_invoice_stats(created: bool, stats: SeedStats) -> None:
        if created:
            stats.invoices_created += 1
        else:
            stats.invoices_updated += 1

    @staticmethod
    def _email_slug(email: str) -> str:
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:10]
        local = re.sub(r"[^a-z0-9]+", "", email.split("@")[0].lower())[:6]
        return f"{local}-{digest}" if local else digest

    @staticmethod
    def _amounts_for_email(email: str) -> dict[str, int]:
        seed = int(hashlib.sha256(email.strip().lower().encode()).hexdigest()[:8], 16)
        deposit = 2_000_000 + (seed % 15) * 100_000
        principal = deposit // 2
        allocate = principal
        return {
            "deposit": deposit,
            "principal": principal,
            "allocate": allocate,
            "return": 20_000 + (seed % 10) * 1_000,
            "fee": 5_000,
            "withdraw": 100_000,
            "return_pending": 12_000,
            "pool_withdraw": 150_000 + (seed % 5) * 10_000,
            "share_bps": 1000 + (seed % 4000),
        }

    def _invoice(
        self,
        merchant,
        code,
        name,
        buyer,
        total,
        loan,
        days,
        due,
        tier,
        pool,
        *,
        industry,
        years,
        review,
        insurance,
        step,
        payout,
        repayment,
        display,
        outstanding,
        funded,
        left,
        funded_at=None,
        closes=None,
        repayment_amount=0,
        inactive=False,
    ):
        invoice, created = Invoice.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "title": name,
                "merchant": merchant,
                "buyer_name": buyer,
                "industry": industry,
                "country": "Nigeria",
                "years_in_operation_snapshot": years,
                "total_amount_cents": total,
                "loan_amount_cents": loan,
                "duration_days": days,
                "due_date": due,
                "apr_bps": 1800,
                "risk_tier": tier,
                "pool": pool,
                "review_status": review,
                "insurance_status": insurance,
                "finance_step": step,
                "payout_status": payout,
                "repayment_state": repayment,
                "display_status": display,
                "repayment_amount_cents": repayment_amount or loan,
                "outstanding_cents": outstanding,
                "funded_amount_cents": funded,
                "amount_left_cents": left,
                "funding_closes_at": closes,
                "funded_at": funded_at,
                "inactive": inactive,
            },
        )
        return invoice, created

    def _stamp(self, model, pk, when):
        model.objects.filter(pk=pk).update(created_at=when)

    def _deposit(self, user, amount, when, pool, key, stats: SeedStats):
        intent, _created = PaymentIntent.objects.get_or_create(
            idempotency_key=f"{PREFIX}-intent-{key}",
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
            destination_label="Wallet deposit",
            pool=pool,
            payment_intent=intent,
            idempotency_key=f"{PREFIX}-tx-{key}",
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        stats.bump_ledger()

    def _withdraw(self, user, amount, when, key, stats: SeedStats, payout=None, successful=True):
        intent, _created = PaymentIntent.objects.get_or_create(
            idempotency_key=f"{PREFIX}-intent-{key}",
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.WITHDRAWAL,
                "amount_cents": amount,
                "status": PaymentIntent.Status.SUCCESSFUL,
                "processor": "dummy",
                "processor_ref": key,
                "payout_method": payout,
                "settled_at": when,
            },
        )
        self._stamp(PaymentIntent, intent.pk, when)
        if not successful:
            return intent
        tx = debit_available(
            user,
            amount,
            tx_type=BalanceTransaction.Type.WITHDRAWAL,
            destination_label="Wallet withdrawal",
            payment_intent=intent,
            idempotency_key=f"{PREFIX}-tx-{key}",
        )
        self._stamp(BalanceTransaction, tx.pk, when)
        stats.bump_ledger()
        return tx

    def _pending_return(self, user, amount, pool, key, stats: SeedStats):
        balance = get_or_create_balance(user)
        tx, _created = BalanceTransaction.objects.get_or_create(
            idempotency_key=f"{PREFIX}-tx-{key}",
            defaults={
                "balance": balance,
                "type": BalanceTransaction.Type.RETURN,
                "status": BalanceTransaction.Status.PENDING,
                "amount_cents": amount,
                "destination_label": "Return pending distribution",
                "pool": pool,
            },
        )
        if _created:
            stats.bump_ledger()
        return tx

    def _move(
        self,
        user,
        amount,
        tx_type,
        when,
        label,
        key,
        *,
        invoice=None,
        pool=None,
        debit=False,
        hold=False,
        stats: SeedStats | None = None,
    ):
        if debit:
            tx = debit_available(
                user,
                amount,
                tx_type=tx_type,
                destination_label=label,
                invoice=invoice,
                pool=pool,
                idempotency_key=f"{PREFIX}-tx-{key}",
                hold=hold,
            )
        else:
            tx = credit_available(
                user,
                amount,
                tx_type=tx_type,
                destination_label=label,
                invoice=invoice,
                pool=pool,
                idempotency_key=f"{PREFIX}-tx-{key}",
            )
        self._stamp(BalanceTransaction, tx.pk, when)
        if stats is not None:
            stats.bump_ledger()
        return tx
