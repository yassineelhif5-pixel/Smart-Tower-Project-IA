from django.urls import path

from . import views as v

urlpatterns = [
    path("discussions", v.DiscussionListView.as_view()),
    path("discussions/<int:pk>", v.DiscussionDetailView.as_view()),
    path("discussions/<int:pk>/messages", v.MessageListView.as_view()),
    path("discussions/<int:pk>/documents", v.DiscussionDocumentsView.as_view()),
    path("discussions/<int:pk>/synchronize", v.SynchronizeView.as_view()),
    path("messages/<int:pk>", v.MessageDetailView.as_view()),
    path("messages/<int:pk>/retry", v.MessageRetryView.as_view()),
    path("teams/connection-status", v.ConnectionStatusView.as_view()),
    path("teams/oauth/start", v.OAuthStartView.as_view()),
    path("teams/oauth/callback", v.OAuthCallbackView.as_view()),
    path("teams/unlink", v.UnlinkView.as_view()),
    path("teams/joined-teams", v.JoinedTeamsView.as_view()),
    path("teams/teams/<str:team_id>/channels", v.ChannelsView.as_view()),
    path("teams/webhook", v.WebhookView.as_view()),
    path("teams/lifecycle", v.LifecycleView.as_view()),
    path("admin/teams", v.TeamsAdminView.as_view()),
    path("admin/teams/check", v.TeamsAdminCheckView.as_view()),
    path("me/notification-preferences", v.NotificationPreferencesView.as_view()),
]
