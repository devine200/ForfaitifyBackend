from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.models import EmailOtp, NotificationPreference, UserSession
from accounts.otp import OtpError, issue_otp, verify_otp
from accounts.serializers import (
    EmailOtpSerializer,
    EmailSerializer,
    LoginSerializer,
    MeSerializer,
    NotificationPreferenceSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSessionSerializer,
    ensure_profile,
    is_at_least_18,
    issue_tokens_for,
)
User = get_user_model()

INVALID_LOGIN = "Invalid email or password."


def _otp_error(exc: OtpError, status_code=400):
    return Response({"detail": str(exc), "code": exc.code}, status=status_code)


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = RegisterSerializer(data=request.data)
        if not ser.is_valid():
            dob_errors = ser.errors.get("date_of_birth")
            if dob_errors:
                return Response({"detail": str(dob_errors[0]), "code": "underage"}, status=400)
            return Response(ser.errors, status=400)
        data = ser.validated_data
        email = data["email"].strip().lower()

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": data["full_name"],
                "country": data["country"],
                "phone": data["phone"],
                "date_of_birth": data["date_of_birth"],
                "is_active": False,
                "email_verified": False,
            },
        )
        role = data["role"]
        if not created:
            if user.email_verified:
                already = (role == "merchant" and user.has_merchant) or (
                    role == "investor" and user.has_investor
                )
                if already:
                    label = "merchant" if role == "merchant" else "investor"
                    return Response(
                        {
                            "detail": f"This email already has {label} access. Sign in instead.",
                            "code": "exists",
                        },
                        status=400,
                    )
                if not user.check_password(data["password"]):
                    return Response(
                        {
                            "detail": "Enter the password for this account to add the other role.",
                            "code": "password",
                        },
                        status=400,
                    )
                # The date in this form is already 18+. Replace a missing or underage
                # saved date so an earlier signup does not block every later attempt.
                if not user.date_of_birth or not is_at_least_18(user.date_of_birth):
                    user.date_of_birth = data["date_of_birth"]
                    user.save(update_fields=["date_of_birth", "updated_at"])
                if role == "investor":
                    try:
                        issue_otp(email, EmailOtp.Purpose.SIGNUP)
                    except OtpError as exc:
                        return _otp_error(exc)
                    return Response(
                        {
                            "detail": "Verification code sent.",
                            "code": "otp_required",
                            "email": email,
                        },
                        status=status.HTTP_201_CREATED,
                    )
                ensure_profile(user, role, business_name=data.get("business_name"))
                return Response(
                    {
                        "detail": "Merchant access was added to your account. Sign in to continue.",
                        "code": "role_added",
                        "email": email,
                    }
                )
            user.full_name = data["full_name"]
            user.country = data["country"]
            user.phone = data["phone"]
            user.date_of_birth = data["date_of_birth"]
            user.is_active = False
            user.save()

        ensure_profile(user, role, business_name=data.get("business_name"))
        user.set_password(data["password"])
        user.save(update_fields=["password"])

        try:
            issue_otp(email, EmailOtp.Purpose.SIGNUP)
        except OtpError as exc:
            return _otp_error(exc)

        return Response(
            {"detail": "Verification code sent.", "email": email},
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = EmailOtpSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Invalid or expired code.", "code": "otp_invalid"}, status=400)
        try:
            verify_otp(email, EmailOtp.Purpose.SIGNUP, ser.validated_data["otp"], consume=True)
        except OtpError as exc:
            return _otp_error(exc)

        if not user.email_verified or not user.is_active:
            user.is_active = True
            user.email_verified = True
            user.save(update_fields=["is_active", "email_verified", "updated_at"])
        return Response(issue_tokens_for(user))


class ResendOtpView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = EmailSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        user = User.objects.filter(email=email).first()
        pending_investor = user is not None and user.email_verified and not user.has_investor
        if user is None or (user.email_verified and not pending_investor):
            return Response({"detail": "If an unverified account exists, a new code was sent."})
        try:
            issue_otp(email, EmailOtp.Purpose.SIGNUP)
        except OtpError as exc:
            return _otp_error(exc)
        return Response({"detail": "Verification code sent."})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        role = ser.validated_data["role"]
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": INVALID_LOGIN, "code": "auth_error"}, status=400)

        password = ser.validated_data["password"]
        if not user.check_password(password):
            return Response({"detail": INVALID_LOGIN, "code": "auth_error"}, status=400)

        if user.account_status == "suspended":
            return Response({"detail": "Account suspended.", "code": "inactive"}, status=403)

        if not user.email_verified:
            return Response(
                {
                    "detail": "Verify your email to finish creating this account.",
                    "code": "email_unverified",
                },
                status=403,
            )

        if role == "admin" and not user.is_admin:
            return Response({"detail": "Not an admin account.", "code": "role"}, status=403)
        if role == "merchant" and not user.has_merchant:
            return Response(
                {
                    "detail": "This account does not have merchant access yet. Create a merchant account with the same email to add it.",
                    "code": "role",
                },
                status=403,
            )
        if role == "investor" and not user.has_investor:
            return Response(
                {
                    "detail": "This account does not have investor access yet. Create an investor account with the same email to add it.",
                    "code": "role",
                },
                status=403,
            )

        if not user.is_active:
            return Response({"detail": "Account inactive.", "code": "inactive"}, status=403)

        UserSession.objects.create(
            user=user,
            device_label=request.META.get("HTTP_USER_AGENT", "")[:255],
            ip=request.META.get("REMOTE_ADDR"),
        )
        return Response(issue_tokens_for(user))


class LogoutView(APIView):
    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except Exception:
                pass
        return Response({"detail": "Logged out."})


class InvestorAgreementView(APIView):
    """Record acceptance, then open the investor profile."""

    def post(self, request):
        if request.data.get("accepted") is not True:
            return Response(
                {"detail": "Accept the investor agreement to continue.", "code": "agreement"},
                status=400,
            )
        if request.user.date_of_birth and not is_at_least_18(request.user.date_of_birth):
            return Response(
                {"detail": "You must be at least 18 years old.", "code": "underage"},
                status=400,
            )
        ensure_profile(request.user, "investor")
        user = User.objects.get(pk=request.user.pk)
        profile = user.investor_profile
        if profile.agreement_accepted_at is None:
            profile.agreement_accepted_at = timezone.now()
            profile.save(update_fields=["agreement_accepted_at", "updated_at"])
        return Response(MeSerializer(user).data)


class AddAccountRoleView(APIView):
    """Attach the other marketplace role to the signed-in account."""

    def post(self, request):
        role = str(request.data.get("role") or "").lower()
        if role not in ("merchant", "investor"):
            return Response({"detail": "role must be merchant or investor."}, status=400)
        user = User.objects.get(pk=request.user.pk)
        submitted = request.data.get("date_of_birth")
        if submitted:
            born = RegisterSerializer().fields["date_of_birth"].to_internal_value(submitted)
            if not is_at_least_18(born):
                return Response(
                    {"detail": "You must be at least 18 years old.", "code": "underage"},
                    status=400,
                )
            user.date_of_birth = born
            user.save(update_fields=["date_of_birth", "updated_at"])
        elif user.date_of_birth and not is_at_least_18(user.date_of_birth):
            return Response(
                {
                    "detail": "Add a date of birth showing you are at least 18 years old.",
                    "code": "underage",
                },
                status=400,
            )
        ensure_profile(user, role)
        user = User.objects.get(pk=user.pk)
        return Response(MeSerializer(user).data)


class ContinueVerificationView(APIView):
    """Send a signup OTP after a correct password on an unverified account."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        user = User.objects.filter(email=email).first()
        if user is None or not user.check_password(ser.validated_data["password"]):
            return Response({"detail": INVALID_LOGIN, "code": "auth_error"}, status=400)
        if user.email_verified:
            return Response({"detail": "Email is already verified.", "code": "verified"}, status=400)
        try:
            issue_otp(email, EmailOtp.Purpose.SIGNUP)
        except OtpError as exc:
            return _otp_error(exc)
        return Response({"detail": "Verification code sent."})


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = EmailSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        user = User.objects.filter(email=email, email_verified=True).first()
        if user is not None:
            try:
                issue_otp(email, EmailOtp.Purpose.PASSWORD_RESET)
            except OtpError as exc:
                return _otp_error(exc)
        return Response({"detail": "If an account exists, a reset code was sent."})


class VerifyResetOtpView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = EmailOtpSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            verify_otp(
                ser.validated_data["email"],
                EmailOtp.Purpose.PASSWORD_RESET,
                ser.validated_data["otp"],
                consume=False,
            )
        except OtpError as exc:
            return _otp_error(exc)
        return Response({"detail": "OTP verified."})


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = ResetPasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].strip().lower()
        try:
            verify_otp(email, EmailOtp.Purpose.PASSWORD_RESET, ser.validated_data["otp"], consume=True)
        except OtpError as exc:
            return _otp_error(exc)
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "Invalid or expired code.", "code": "otp_invalid"}, status=400)
        user.set_password(ser.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        ser = ProfileUpdateSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        user = request.user
        for field in ("full_name", "phone", "country", "avatar_url"):
            if field in data:
                setattr(user, field, data[field])
        user.save()
        if hasattr(user, "merchant_profile"):
            mp = user.merchant_profile
            for field in ("business_name", "industry", "years_in_operation"):
                if field in data:
                    setattr(mp, field, data[field])
            mp.save()
        return Response(MeSerializer(user).data)


class SessionListView(generics.ListAPIView):
    serializer_class = UserSessionSerializer

    def get_queryset(self):
        return UserSession.objects.filter(user=self.request.user, revoked_at__isnull=True)


class SessionRevokeView(APIView):
    def delete(self, request, session_id):
        session = UserSession.objects.filter(user=request.user, id=session_id).first()
        if not session:
            return Response({"detail": "Not found."}, status=404)
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])
        return Response(status=204)


class NotificationPreferenceView(APIView):
    def get(self, request):
        qs = NotificationPreference.objects.filter(user=request.user)
        return Response(NotificationPreferenceSerializer(qs, many=True).data)

    def patch(self, request):
        items = request.data if isinstance(request.data, list) else [request.data]
        out = []
        for item in items:
            ser = NotificationPreferenceSerializer(data=item)
            ser.is_valid(raise_exception=True)
            obj, _ = NotificationPreference.objects.update_or_create(
                user=request.user,
                role_scope=ser.validated_data["role_scope"],
                category=ser.validated_data["category"],
                defaults={"enabled": ser.validated_data["enabled"]},
            )
            out.append(obj)
        return Response(NotificationPreferenceSerializer(out, many=True).data)


class RefreshView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]
