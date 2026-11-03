from django.urls import path

from invoices import views

urlpatterns = [
    path("merchant/dashboard", views.MerchantDashboardView.as_view()),
    path("merchant/invoices", views.MerchantInvoiceListCreateView.as_view()),
    path("merchant/invoices/<uuid:pk>", views.MerchantInvoiceDetailView.as_view()),
    path("merchant/invoices/<uuid:pk>/documents", views.MerchantInvoiceDocumentView.as_view()),
    path("merchant/invoices/<uuid:pk>/withdraw-funding", views.MerchantWithdrawFundingView.as_view()),
    path("merchant/invoices/<uuid:pk>/repay", views.MerchantRepayView.as_view()),
    path("merchant/pools", views.MerchantPoolBrowseView.as_view()),
    path("investor/dashboard", views.InvestorDashboardView.as_view()),
    path("investor/invoices", views.InvestorInvoiceListView.as_view()),
    path("investor/invoices/<uuid:pk>", views.InvestorInvoiceDetailView.as_view()),
    path("admin/dashboard", views.AdminDashboardView.as_view()),
    path("admin/invoices", views.AdminInvoiceListView.as_view()),
    path("admin/invoices/<uuid:pk>", views.AdminInvoiceDetailView.as_view()),
    path("admin/invoices/<uuid:pk>/review", views.AdminInvoiceReviewView.as_view()),
    path("admin/invoices/<uuid:pk>/insurance", views.AdminInvoiceInsuranceView.as_view()),
    path("admin/invoices/<uuid:pk>/fund", views.AdminInvoiceFundView.as_view()),
]
