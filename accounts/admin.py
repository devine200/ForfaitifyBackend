from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import InvestorProfile, MerchantProfile, NotificationPreference, User, UserSession


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "is_admin", "is_active", "account_status")
    search_fields = ("email", "full_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "country", "date_of_birth", "avatar_url")}),
        ("Flags", {"fields": ("is_active", "is_staff", "is_admin", "is_superuser", "account_status", "email_verified", "supabase_uid")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "is_admin")}),
    )
    filter_horizontal = ("groups", "user_permissions")


admin.site.register(MerchantProfile)
admin.site.register(InvestorProfile)
admin.site.register(UserSession)
admin.site.register(NotificationPreference)
