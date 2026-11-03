"""Local demo data: verified accounts, invoices, pools, and ledger activity."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import InvestorProfile, MerchantProfile
from balances.models import BalanceTransaction
from balances.services import credit_available, debit_available, get_or_create_balance
from cosign.models import CoSigner, CosignInvite
from epochs.models import Epoch, EpochDistribution
from invoices.models import Invoice, InvoiceAcknowledgement, InvoiceDocument
from kyc.models import KycRecord, ReviewStatus
from payments.models import PaymentIntent, PayoutMethod
from pools.models import Pool, PoolLoanTier, PoolPosition, PoolWithdrawalRequest

User = get_user_model()

PASSWORD = "Demo-pass-2026"
PREFIX = "demo-seed"


class Command(BaseCommand):
    help = "Create verified demo users, invoices at each stage, pools, and ledger activity."

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        admin = self._user(
            "demo-admin@forfaitify.test",
            "Ada Okoye",
            admin=True,
        )
        merchant_a = self._user("demo-merchant@forfaitify.test", "Amaka Okonkwo")
        merchant_b = self._user("demo-merchant-b@forfaitify.test", "Chinedu Bello")
        investor_a = self._user("demo-investor@forfaitify.test", "Ifeanyi Cole")
        investor_b = self._user("demo-investor-b@forfaitify.test", "Ngozi Adeyemi")

        profile_a = self._merchant(merchant_a, "Lagos Grain Co", "Agriculture", 8)
        profile_b = self._merchant(merchant_b, "Harbor Textiles", "Manufacturing", 5)
        investor_profile_a = self._investor(investor_a)
        investor_profile_b = self._investor(investor_b)
        self._kyc(admin, "")
        self._kyc(merchant_a, "kyb")
        self._kyc(merchant_b, "kyb")
        self._kyc(investor_a, "kyc")
        self._kyc(investor_b, "kyc")
        for user in (admin, merchant_a, merchant_b, investor_a, investor_b):
            get_or_create_balance(user)

        central = self._pool(
            "West Africa Receivables",
            Pool.Type.CENTRALIZED,
            investor_profile_a,
            admin,
            public=True,
            target=50_000_000,
            strategy="Short receivables from verified merchants in Nigeria and Ghana.",
        )
        custom = self._pool(
            "Harbor Custom Book",
            Pool.Type.CUSTOM,
            investor_profile_a,
            investor_a,
            public=False,
            target=20_000_000,
            strategy="A single-investor book for Harbor Textiles receivables.",
        )
        tier_30 = self._tier(central, "30 day", 30, 1200, 100_000, 2_000_000)
        self._tier(central, "60 day", 60, 1800, 200_000, 5_000_000)
        tier_90 = self._tier(central, "90 day", 90, 2400, 500_000, 10_000_000)
        custom_tier = self._tier(custom, "45 day", 45, 1600, 100_000, 3_000_000)

        self._epoch(central, 1, Epoch.State.CLOSED, now - timedelta(days=120), now - timedelta(days=90))
        epoch_paid = self._epoch(
            central, 2, Epoch.State.RETURNS_DISTRIBUTED, now - timedelta(days=70), now - timedelta(days=40)
        )
        self._epoch(central, 3, Epoch.State.FUNDING_OPEN, now - timedelta(days=10), now + timedelta(days=20))
        self._epoch(custom, 1, Epoch.State.CAPITAL_DEPLOYED, now - timedelta(days=20), now + timedelta(days=25))

        position_a = self._position(central, investor_profile_a, 2_500_000)
        self._position(custom, investor_profile_a, 800_000)
        self._position(central, investor_profile_b, 1_200_000)
        EpochDistribution.objects.update_or_create(
            epoch=epoch_paid,
            position=position_a,
            defaults={"return_cents": 31_000, "posted_to_balance": True},
        )
        PoolWithdrawalRequest.objects.get_or_create(
            pool=central,
            investor=investor_profile_b,
            status=PoolWithdrawalRequest.Status.PENDING,
            defaults={"amount_cents": 200_000, "pool_share_bps_snapshot": 3200},
        )

        payout_a = self._payout(merchant_a, "GTBank · Lagos Grain", "0123456789")
        self._payout(merchant_b, "Access Bank · Harbor", "9876543210")

        pending = self._invoice(
            profile_a,
            "DEMO-INV-01",
            "Grain shipment · pending review",
            "Shoprite Nigeria",
            1_200_000,
            1_000_000,
            30,
            now.date() + timedelta(days=40),
            tier_30,
            None,
            review=Invoice.ReviewStatus.PENDING_REVIEW,
            insurance=Invoice.InsuranceStatus.PENDING,
            step=Invoice.FinanceStep.CREATED,
            payout=Invoice.PayoutStatus.NONE,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.PENDING,
            outstanding=0,
            funded=0,
            left=1_000_000,
        )
        funding = self._invoice(
            profile_a,
            "DEMO-INV-02",
            "Cocoa offtake · open for funding",
            "Olam Nigeria",
            2_400_000,
            2_000_000,
            60,
            now.date() + timedelta(days=70),
            tier_90,
            central,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FUNDING,
            payout=Invoice.PayoutStatus.NONE,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.PROCESSING,
            outstanding=0,
            funded=0,
            left=2_000_000,
            closes=now + timedelta(days=14),
        )
        funded = self._invoice(
            profile_a,
            "DEMO-INV-03",
            "Maize supply · funded, ready to withdraw",
            "Flour Mills",
            1_250_000,
            1_000_000,
            30,
            now.date() + timedelta(days=24),
            tier_30,
            central,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_FUNDED,
            payout=Invoice.PayoutStatus.READY,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=1_060_000,
            funded=1_000_000,
            left=0,
            funded_at=now - timedelta(days=6),
            repayment_amount=1_060_000,
        )
        withdrawn = self._invoice(
            profile_a,
            "DEMO-INV-04",
            "Rice contract · withdrawn, current",
            "Dangote Foods",
            900_000,
            750_000,
            45,
            now.date() + timedelta(days=18),
            tier_30,
            central,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FUNDING_WITHDRAWN,
            payout=Invoice.PayoutStatus.SETTLED,
            repayment=Invoice.RepaymentState.CURRENT,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=400_000,
            funded=750_000,
            left=0,
            funded_at=now - timedelta(days=28),
            repayment_amount=795_000,
        )
        overdue = self._invoice(
            profile_a,
            "DEMO-INV-05",
            "Palm oil · matured and overdue",
            "PZ Cussons",
            650_000,
            500_000,
            30,
            now.date() - timedelta(days=12),
            tier_30,
            central,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_MATURED,
            payout=Invoice.PayoutStatus.SETTLED,
            repayment=Invoice.RepaymentState.OVERDUE,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=530_000,
            funded=500_000,
            left=0,
            funded_at=now - timedelta(days=50),
            repayment_amount=530_000,
        )
        repaid = self._invoice(
            profile_a,
            "DEMO-INV-06",
            "Sorghum lot · repaid",
            "Nestle Nigeria",
            720_000,
            600_000,
            30,
            now.date() - timedelta(days=20),
            tier_30,
            central,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_REPAID,
            payout=Invoice.PayoutStatus.SETTLED,
            repayment=Invoice.RepaymentState.REPAID,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=0,
            funded=600_000,
            left=0,
            funded_at=now - timedelta(days=55),
            repayment_amount=636_000,
        )
        self._invoice(
            profile_a,
            "DEMO-INV-07",
            "Rejected receivable",
            "Unknown buyer",
            300_000,
            250_000,
            30,
            now.date() + timedelta(days=30),
            None,
            None,
            review=Invoice.ReviewStatus.REJECTED,
            insurance=Invoice.InsuranceStatus.REJECTED,
            step=Invoice.FinanceStep.CREATED,
            payout=Invoice.PayoutStatus.NONE,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.REJECTED,
            outstanding=0,
            funded=0,
            left=250_000,
            inactive=True,
        )
        custom_open = self._invoice(
            profile_b,
            "DEMO-INV-08",
            "Fabric run · custom pool funding",
            "Shoprite Nigeria",
            1_800_000,
            1_500_000,
            45,
            now.date() + timedelta(days=50),
            custom_tier,
            custom,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FUNDING,
            payout=Invoice.PayoutStatus.NONE,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.PROCESSING,
            outstanding=0,
            funded=0,
            left=1_500_000,
            closes=now + timedelta(days=12),
        )
        pending_payout = self._invoice(
            profile_b,
            "DEMO-INV-09",
            "Uniform order · payout pending",
            "GTBank",
            480_000,
            400_000,
            30,
            now.date() + timedelta(days=22),
            custom_tier,
            custom,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_FUNDED,
            payout=Invoice.PayoutStatus.PENDING,
            repayment=Invoice.RepaymentState.NOT_STARTED,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=424_000,
            funded=400_000,
            left=0,
            funded_at=now - timedelta(days=4),
            repayment_amount=424_000,
        )
        self._invoice(
            profile_b,
            "DEMO-INV-10",
            "Thread purchase · repaid",
            "Cadbury Nigeria",
            360_000,
            300_000,
            30,
            now.date() - timedelta(days=8),
            custom_tier,
            custom,
            review=Invoice.ReviewStatus.APPROVED,
            insurance=Invoice.InsuranceStatus.VERIFIED,
            step=Invoice.FinanceStep.FINANCE_REPAID,
            payout=Invoice.PayoutStatus.SETTLED,
            repayment=Invoice.RepaymentState.REPAID,
            display=Invoice.DisplayStatus.SUCCESSFUL,
            outstanding=0,
            funded=300_000,
            left=0,
            funded_at=now - timedelta(days=40),
            repayment_amount=318_000,
        )

        invite, _ = CosignInvite.objects.get_or_create(
            invoice=funding,
            invitee_email=merchant_b.email,
            defaults={
                "token": "demo-cosign-harbor",
                "inviter": profile_a,
                "invitee_name": merchant_b.full_name,
                "status": CosignInvite.Status.PENDING,
                "expires_at": now + timedelta(days=7),
            },
        )
        CoSigner.objects.get_or_create(
            invoice=funding,
            party_user=merchant_b,
            defaults={
                "invite": invite,
                "party_name": merchant_b.full_name,
                "status": CoSigner.Status.PENDING,
            },
        )
        InvoiceDocument.objects.get_or_create(
            invoice=funding,
            name="Offtake contract.pdf",
            defaults={"visibility": InvoiceDocument.Visibility.AVAILABLE},
        )
        for invoice in (funding, funded, withdrawn, overdue, repaid, custom_open, pending_payout):
            for kind, _label in InvoiceAcknowledgement.Kind.choices:
                InvoiceAcknowledgement.objects.get_or_create(invoice=invoice, kind=kind)
        InvoiceDocument.objects.get_or_create(
            invoice=pending,
            name="Delivery note.pdf",
            defaults={"visibility": InvoiceDocument.Visibility.AVAILABLE},
        )

        self._deposit(investor_a, 4_000_000, now - timedelta(days=55), central, "demo-dep-a-old")
        self._deposit(investor_a, 1_500_000, now - timedelta(days=8), central, "demo-dep-a-new")
        self._deposit(investor_b, 2_000_000, now - timedelta(days=20), central, "demo-dep-b")
        self._move(
            investor_a,
            2_500_000,
            BalanceTransaction.Type.POOL_ALLOCATE,
            now - timedelta(days=40),
            "Allocated to West Africa Receivables",
            "demo-alloc-a-central",
            pool=central,
            debit=True,
        )
        self._move(
            investor_a,
            800_000,
            BalanceTransaction.Type.POOL_ALLOCATE,
            now - timedelta(days=18),
            "Allocated to Harbor Custom Book",
            "demo-alloc-a-custom",
            pool=custom,
            debit=True,
        )
        self._move(
            investor_b,
            1_200_000,
            BalanceTransaction.Type.POOL_ALLOCATE,
            now - timedelta(days=12),
            "Allocated to West Africa Receivables",
            "demo-alloc-b-central",
            pool=central,
            debit=True,
        )
        for months_ago, amount in ((5, 18_000), (4, 22_000), (3, 25_000), (2, 31_000), (1, 28_000), (0, 36_000)):
            self._move(
                investor_a,
                amount,
                BalanceTransaction.Type.RETURN,
                self._months_ago(months_ago),
                "Pool return",
                f"demo-return-a-{months_ago}",
                pool=central,
            )
        self._move(
            investor_a,
            12_000,
            BalanceTransaction.Type.RETURN,
            now - timedelta(days=2),
            "Pool return",
            "demo-return-a-week",
            pool=central,
        )
        self._move(
            investor_b,
            15_000,
            BalanceTransaction.Type.RETURN,
            now - timedelta(days=3),
            "Pool return",
            "demo-return-b",
            pool=central,
        )
        self._move(
            investor_a,
            5_000,
            BalanceTransaction.Type.FEE,
            now - timedelta(days=5),
            "Platform fee",
            "demo-fee-a",
            pool=central,
            debit=True,
        )
        self._withdraw(investor_a, 200_000, now - timedelta(days=6), "demo-wd-a", successful=True)
        self._move(
            investor_a,
            100_000,
            BalanceTransaction.Type.WITHDRAWAL,
            now - timedelta(days=1),
            "Withdrawal on hold",
            "demo-wd-a-hold",
            debit=True,
            hold=True,
        )
        self._pending_return(investor_a, 15_000, central, "demo-return-a-pending")

        self._deposit(merchant_a, 500_000, now - timedelta(days=60), None, "demo-dep-m-old")
        self._move(
            merchant_a,
            funded.funded_amount_cents,
            BalanceTransaction.Type.FUNDING,
            now - timedelta(days=6),
            f"Invoice funding {funded.code}",
            "demo-fund-03",
            invoice=funded,
            pool=central,
        )
        self._move(
            merchant_a,
            withdrawn.funded_amount_cents,
            BalanceTransaction.Type.FUNDING,
            now - timedelta(days=28),
            f"Invoice funding {withdrawn.code}",
            "demo-fund-04",
            invoice=withdrawn,
            pool=central,
        )
        self._withdraw(merchant_a, withdrawn.funded_amount_cents, now - timedelta(days=27), "demo-wd-m-04", payout_a)
        self._move(
            merchant_a,
            395_000,
            BalanceTransaction.Type.REPAYMENT,
            now - timedelta(days=20),
            f"Repayment {withdrawn.code}",
            "demo-repay-04",
            invoice=withdrawn,
            debit=True,
        )
        self._move(
            merchant_a,
            overdue.funded_amount_cents,
            BalanceTransaction.Type.FUNDING,
            now - timedelta(days=50),
            f"Invoice funding {overdue.code}",
            "demo-fund-05",
            invoice=overdue,
            pool=central,
        )
        self._withdraw(merchant_a, overdue.funded_amount_cents, now - timedelta(days=48), "demo-wd-m-05", payout_a)
        self._move(
            merchant_a,
            130_000,
            BalanceTransaction.Type.REPAYMENT,
            now - timedelta(days=10),
            f"Repayment {overdue.code}",
            "demo-repay-05",
            invoice=overdue,
            debit=True,
        )
        self._move(
            merchant_a,
            repaid.funded_amount_cents,
            BalanceTransaction.Type.FUNDING,
            now - timedelta(days=55),
            f"Invoice funding {repaid.code}",
            "demo-fund-06",
            invoice=repaid,
            pool=central,
        )
        self._withdraw(merchant_a, repaid.funded_amount_cents, now - timedelta(days=54), "demo-wd-m-06", payout_a)
        self._move(
            merchant_a,
            repaid.repayment_amount_cents,
            BalanceTransaction.Type.REPAYMENT,
            now - timedelta(days=21),
            f"Repayment {repaid.code}",
            "demo-repay-06",
            invoice=repaid,
            debit=True,
        )
        self._move(
            merchant_a,
            8_000,
            BalanceTransaction.Type.FEE,
            now - timedelta(days=21),
            "Financing fee",
            "demo-fee-m",
            invoice=repaid,
            debit=True,
        )
        self._pending_withdrawal(merchant_b, 150_000, "demo-wd-b-review")

        self.stdout.write(self.style.SUCCESS("Demo data is ready. Password for every demo account: " + PASSWORD))
        self.stdout.write("Admin     demo-admin@forfaitify.test")
        self.stdout.write("Merchant  demo-merchant@forfaitify.test")
        self.stdout.write("Merchant  demo-merchant-b@forfaitify.test")
        self.stdout.write("Investor  demo-investor@forfaitify.test")
        self.stdout.write("Investor  demo-investor-b@forfaitify.test")

    def _user(self, email, name, *, admin=False):
        user, _created = User.objects.get_or_create(
            email=email,
            defaults={"full_name": name},
        )
        user.full_name = name
        user.country = "Nigeria"
        user.phone = "+2348010000000"
        user.date_of_birth = "1990-04-12"
        user.is_active = True
        user.email_verified = True
        user.is_admin = admin
        user.is_staff = admin
        user.account_status = "active"
        user.set_password(PASSWORD)
        user.save()
        return user

    def _merchant(self, user, business, industry, years):
        profile, _created = MerchantProfile.objects.get_or_create(
            user=user,
            defaults={"business_name": business, "industry": industry, "years_in_operation": years},
        )
        profile.business_name = business
        profile.industry = industry
        profile.years_in_operation = years
        profile.account_status = "active"
        profile.save()
        return profile

    def _investor(self, user):
        profile, _created = InvestorProfile.objects.get_or_create(user=user)
        if profile.agreement_accepted_at is None:
            profile.agreement_accepted_at = timezone.now()
            profile.save(update_fields=["agreement_accepted_at", "updated_at"])
        return profile

    def _kyc(self, user, kind):
        record, _created = KycRecord.objects.get_or_create(
            user=user,
            verification_kind=kind,
        )
        record.provider_status = ReviewStatus.APPROVED
        record.admin_status = ReviewStatus.APPROVED
        record.reviewed_at = timezone.now()
        record.save()

    def _pool(self, name, pool_type, owner, created_by, *, public, target, strategy):
        pool, _created = Pool.objects.get_or_create(
            name=name,
            defaults={
                "type": pool_type,
                "owner_investor": owner,
                "created_by": created_by,
            },
        )
        pool.type = pool_type
        pool.status = Pool.Status.ACTIVE
        pool.closed = False
        pool.owner_investor = owner
        pool.created_by = created_by
        pool.countries = ["Nigeria", "Ghana"]
        pool.industries = ["Agriculture", "Manufacturing"]
        pool.strategy = strategy
        pool.min_deposit_cents = 100_000
        pool.target_size_cents = target
        pool.exposure_limit_percent = 15
        pool.auto_funding = True
        pool.allow_public = public
        pool.target_return_bps = 1800
        pool.save()
        return pool

    def _tier(self, pool, name, days, bps, low, high):
        tier, _created = PoolLoanTier.objects.get_or_create(
            pool=pool,
            name=name,
            defaults={
                "duration_days": days,
                "interest_bps": bps,
                "invoice_min_cents": low,
                "invoice_max_cents": high,
            },
        )
        return tier

    def _epoch(self, pool, index, state, start, end):
        epoch, _created = Epoch.objects.get_or_create(
            pool=pool,
            index=index,
            defaults={"starts_at": start, "ends_at": end, "state": state},
        )
        epoch.starts_at = start
        epoch.ends_at = end
        epoch.state = state
        if state == Epoch.State.RETURNS_DISTRIBUTED:
            epoch.withdrawal_window_start = end
            epoch.withdrawal_window_end = end + timedelta(days=7)
        epoch.save()
        return epoch

    def _position(self, pool, investor, principal):
        position, _created = PoolPosition.objects.update_or_create(
            pool=pool,
            investor=investor,
            defaults={"principal_cents": principal},
        )
        return position

    def _payout(self, user, label, ref):
        method, _created = PayoutMethod.objects.get_or_create(
            user=user,
            label=label,
            defaults={"account_ref": ref, "is_default": True},
        )
        return method

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
        invoice, _created = Invoice.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "title": name,
                "merchant": merchant,
                "buyer_name": buyer,
                "industry": merchant.industry,
                "country": "Nigeria",
                "years_in_operation_snapshot": merchant.years_in_operation,
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
        return invoice

    def _months_ago(self, months):
        now = timezone.now()
        index = now.month - 1 - months
        year = now.year + index // 12
        month = index % 12 + 1
        return now.replace(year=year, month=month, day=12, hour=15, minute=0, second=0, microsecond=0)

    def _stamp(self, model, pk, when):
        model.objects.filter(pk=pk).update(created_at=when)

    def _deposit(self, user, amount, when, pool, key):
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

    def _withdraw(self, user, amount, when, key, payout=None, successful=True):
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
        return tx

    def _pending_withdrawal(self, user, amount, key):
        intent, _created = PaymentIntent.objects.get_or_create(
            idempotency_key=f"{PREFIX}-intent-{key}",
            defaults={
                "user": user,
                "kind": PaymentIntent.Kind.WITHDRAWAL,
                "amount_cents": amount,
                "status": PaymentIntent.Status.PENDING,
                "requires_admin_review": True,
                "processor": "dummy",
                "processor_ref": key,
            },
        )
        return intent

    def _pending_return(self, user, amount, pool, key):
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
        return tx

    def _move(self, user, amount, tx_type, when, label, key, *, invoice=None, pool=None, debit=False, hold=False):
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
        return tx
