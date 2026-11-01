from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts import views as auth
from configuration import views as conf
from projects import views as projects

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
