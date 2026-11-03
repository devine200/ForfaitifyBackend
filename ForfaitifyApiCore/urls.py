from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("kyc.urls")),
    path("api/v1/", include("balances.urls")),
    path("api/v1/", include("payments.urls")),
    path("api/v1/", include("pools.urls")),
    path("api/v1/", include("epochs.urls")),
    path("api/v1/", include("invoices.urls")),
    path("api/v1/", include("cosign.urls")),
    path("api/v1/", include("notifications.urls")),
    path("api/v1/", include("support.urls")),
    path("api/v1/", include("admin_ops.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
