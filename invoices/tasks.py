from celery import shared_task


@shared_task(ignore_result=True)
def sweep_auto_repayments():
    """Hourly: mark overdue, then auto-debit merchant balances against open debts."""
    from accounts.models import MerchantProfile
    from invoices.services import auto_repay_user_invoices, mark_overdue_invoices

    mark_overdue_invoices()
    # Prefer merchants with available balance and outstanding settled invoices.
    merchant_ids = (
        MerchantProfile.objects.filter(
            invoices__payout_status="settled",
            invoices__outstanding_cents__gt=0,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    from accounts.models import User

    count = 0
    for user in User.objects.filter(id__in=merchant_ids).iterator():
        repaid = auto_repay_user_invoices(user)
        count += len(repaid)
    return {"repaid_invoices": count}
