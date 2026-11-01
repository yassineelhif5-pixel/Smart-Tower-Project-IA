from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts import views as auth
from configuration import views as conf
from licensing import views as lic
from projects import views as projects
from tenants import views as tenants

admin_patterns = [
    path("users", conf.UserListView.as_view()),
    path("users/<int:pk>", conf.UserDetailView.as_view()),
    path("users/<int:pk>/reset-password", conf.UserResetPasswordView.as_view()),
    path("users/<int:pk>/access", conf.UserAccessView.as_view()),
    path("projects", conf.AdminProjectsView.as_view()),
    path("roles", conf.RoleListView.as_view()),
    path("roles/<str:code>/permissions", conf.RolePermissionsView.as_view()),
    path("database", conf.DatabaseView.as_view()),
    path("database/test", conf.DatabaseTestView.as_view()),
    path("api/endpoints", conf.EndpointListView.as_view()),
    path("api/stats", conf.ApiStatsView.as_view()),
    path("api/logs", conf.ApiLogView.as_view()),
    path("api/tokens", conf.TokenListView.as_view()),
    path("api/tokens/<int:pk>/revoke", conf.TokenRevokeView.as_view()),
    path("secrets", conf.SecretListView.as_view()),
    path("secrets/<str:key>", conf.SecretDetailView.as_view()),
    path("notifications", conf.NotificationSettingsView.as_view()),
    path("notifications/rules", conf.RulesView.as_view()),
    path("notifications/channels/<str:kind>", conf.ChannelView.as_view()),
    path("notifications/channels/<str:kind>/test", conf.ChannelTestView.as_view()),
    path("audit", conf.AuditView.as_view()),
    path("capabilities", conf.CapabilityMatrixView.as_view()),
    path("users/<int:pk>/capabilities", conf.UserCapabilityView.as_view()),
]

# Espace entreprise : licences, sessions et demandes (selon les droits d'administration délégués).
licensing_patterns = [
    path("overview", lic.OverviewView.as_view()),
    path("licenses", lic.LicenseListView.as_view()),
    path("licenses/<int:pk>/<str:action>", lic.LicenseActionView.as_view()),
    path("sessions", lic.SessionListView.as_view()),
    path("sessions/<int:pk>/revoke", lic.SessionRevokeView.as_view()),
    path("requests", lic.RequestListView.as_view()),
    path("requests/<int:pk>", lic.RequestDetailView.as_view()),
    path("requests/<int:pk>/<str:action>", lic.RequestDetailView.as_view()),
    path("offers", lic.OfferCatalogView.as_view()),
    path("audit", lic.TenantAuditView.as_view()),
]

# Espace Pilote (Super Admin Global) : entreprises, offres, licences, demandes, supervision.
platform_patterns = [
    path("tenants", tenants.TenantListView.as_view()),
    path("tenants/<int:pk>", tenants.TenantDetailView.as_view()),
    path("audit", tenants.PlatformAuditView.as_view()),
    path("dashboard", lic.PilotDashboardView.as_view()),
    path("offers", lic.OfferListView.as_view()),
    path("offers/<int:pk>", lic.OfferDetailView.as_view()),
    path("offers/<int:pk>/versions", lic.VersionCreateView.as_view()),
    path("versions/<int:pk>", lic.VersionDetailView.as_view()),
    path("tenants/<int:pk>/subscription", lic.TenantSubscriptionView.as_view()),
    path("tenants/<int:pk>/allocations", lic.TenantAllocationView.as_view()),
    path("requests", lic.PilotRequestListView.as_view()),
    path("requests/<int:pk>", lic.PilotRequestDetailView.as_view()),
    path("requests/<int:pk>/<str:action>", lic.PilotRequestDetailView.as_view()),
]

api_patterns = [
    path("health", conf.HealthView.as_view()),
    path("auth/csrf", auth.CsrfView.as_view()),
    path("auth/login", auth.LoginView.as_view()),
    path("auth/logout", auth.LogoutView.as_view()),
    path("auth/me", auth.MeView.as_view()),
    path("auth/change-password", auth.ChangePasswordView.as_view()),
    path("projects", projects.ProjectListView.as_view()),
    path("projects/<str:pk>/actions", projects.ProjectActionsView.as_view()),
    path("notifications", conf.MyNotificationsView.as_view()),
    path("admin/", include(admin_patterns)),
    path("platform/", include(platform_patterns)),
    path("licensing/", include(licensing_patterns)),
    path("me/access", lic.MyAccessView.as_view()),
]

# Documentation OpenAPI : administrateurs connectés uniquement (SPECTACULAR_SETTINGS.SERVE_PERMISSIONS).
docs_patterns = [
    path("schema", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="openapi-schema"), name="openapi-docs"),
]

urlpatterns = [
    # Version courante de l'API : la seule documentée et appelée par le frontend.
    path("api/v1/", include(api_patterns + docs_patterns)),
    # Ancien chemin sans version, conservé tel quel pour les applications tierces déjà branchées dessus.
    path("api/", include(api_patterns)),
]
