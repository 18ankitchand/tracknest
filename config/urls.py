from django.contrib import admin
from django.urls import path
from accounts import views
from accounts.admin_views import overview

admin.site.site_header = "TrackNest administration"
admin.site.site_title = "TrackNest admin"
admin.site.index_title = "Manage your expense tracker"

urlpatterns = [
    path("admin/overview/", overview, name="admin_overview"),
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("api/auth/register/", views.register),
    path("api/auth/login/", views.sign_in),
    path("api/auth/logout/", views.sign_out),
    path("api/auth/me/", views.me),
    path("api/finance/state/", views.financial_state),
    path("api/finance/budget/", views.set_budget),
    path("api/finance/transactions/", views.add_financial_transaction),
    path("api/finance/transactions/<int:transaction_id>/edit/", views.edit_financial_transaction),
]
