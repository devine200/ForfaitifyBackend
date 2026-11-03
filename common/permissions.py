from rest_framework.permissions import BasePermission

from kyc.models import KycRecord, ReviewStatus


def _kind_approved(user, kind: str) -> bool:
    return KycRecord.objects.filter(
        user=user,
        verification_kind=kind,
        provider_status=ReviewStatus.APPROVED,
        admin_status=ReviewStatus.APPROVED,
    ).exists()


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "is_admin", False))


class IsMerchant(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and hasattr(user, "merchant_profile")
        )


class IsInvestor(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and hasattr(user, "investor_profile")
        )


class IsMerchantOrInvestor(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return hasattr(user, "merchant_profile") or hasattr(user, "investor_profile")


class HasApprovedVerification(BasePermission):
    """Didit plus admin approval for one check. Subclasses set required_kind."""

    required_kind = ""
    message = "Verification must be approved by Didit and an admin before this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_admin", False):
            return True
        return bool(self.required_kind) and _kind_approved(user, self.required_kind)


class HasApprovedKyc(HasApprovedVerification):
    required_kind = "kyc"
    message = "Investor KYC must be approved by Didit and an admin before this action."


class HasApprovedKyb(HasApprovedVerification):
    required_kind = "kyb"
    message = "Merchant KYB must be approved by Didit and an admin before this action."


class HasApprovedActorVerification(BasePermission):
    """Shared money endpoints: KYC for investors, KYB for merchants."""

    message = "Verification must be approved by Didit and an admin before this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_admin", False):
            return True
        if user.has_merchant and not user.has_investor:
            return _kind_approved(user, "kyb")
        if user.has_investor and not user.has_merchant:
            return _kind_approved(user, "kyc")
        role = ""
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            role = str(data.get("role") or "").lower()
        if role == "merchant":
            return _kind_approved(user, "kyb")
        if role == "investor":
            return _kind_approved(user, "kyc")
        return False


class IsOwnerOrAdmin(BasePermission):
    """Object-level: object.user == request.user or admin."""

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "is_admin", False):
            return True
        owner = getattr(obj, "user", None) or getattr(obj, "requester", None)
        return owner == request.user
