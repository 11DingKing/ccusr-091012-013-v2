from django.urls import include, path

urlpatterns = [
    path("api/auth/", include("apps.authentication.urls")),
    path("api/", include("apps.warehouse.urls")),
    path("api/", include("apps.personnel.urls")),
    path("api/", include("apps.reports.urls")),
]
