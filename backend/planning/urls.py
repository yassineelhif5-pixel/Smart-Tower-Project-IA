from django.urls import path

from . import views as v

urlpatterns = [
    path("events", v.EventListView.as_view()),
    path("events/<int:pk>", v.EventDetailView.as_view()),
    path("events/<int:pk>/reminders", v.ReminderListView.as_view()),
    path("reminders/<int:pk>", v.ReminderDetailView.as_view()),
    path("assignments", v.AssignmentListView.as_view()),
    path("workload", v.WorkloadView.as_view()),
    path("conflicts", v.ConflictListView.as_view()),
    path("dashboard", v.DashboardView.as_view()),
    path("portfolio", v.PortfolioView.as_view()),
    path("settings", v.SettingsView.as_view()),
    path("people", v.PeopleView.as_view()),
    path("feed-token", v.FeedTokenView.as_view()),
    path("feed/<str:token>.ics", v.FeedView.as_view()),
]
