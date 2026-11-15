from django.urls import path

from . import client_portal as cp
from . import client_rates as cr
from . import portal_docs as pd
from . import licence_report as lr
from . import doc_info as di
from . import template_views as tv
from . import views as v

urlpatterns = [
    path("client-portal/timesheets", cp.PortalTimesheetsView.as_view()),
    path("client-portal/billing", cp.PortalBillingView.as_view()),
    path("client-portal/orders", cp.PortalOrdersView.as_view()),
    path("client-portal/orders/<str:order_id>/decision", cp.PortalOrderDecisionView.as_view()),
    path("client-portal/recap", cp.PortalRecapView.as_view()),
    path("client-portal/budget-report", pd.BudgetReportView.as_view()),
    path("client-portal/orders/<str:order_id>/document", pd.OrderDocumentView.as_view()),
    path("client-space/library", pd.LibraryView.as_view()),
    path("client-portal/licences", lr.LicenceReportView.as_view()),
    path("client-space/doc-info", di.DocInfoView.as_view()),
    path("client-space", v.ClientSpaceView.as_view()),
    path("client-space/documents/<str:doc_id>", v.ClientDocumentView.as_view()),
    path("client-space/generate", v.GenerateView.as_view()),
    path("client-space/time-validation", v.TimeValidationView.as_view()),
    path("client-space/support", v.SupportView.as_view()),
    path("client-space/billing-settings", v.BillingSettingsView.as_view()),
    path("client-space/rates", cr.ClientRatesView.as_view()),
    path("client-space/rates/visibility", cr.ClientAmountsVisibilityView.as_view()),
    path("client-space/invoice-templates", tv.InvoiceTemplatesView.as_view()),
    path("client-space/invoice-templates/sample", tv.InvoiceTemplateSampleView.as_view()),
    path("client-space/invoice-templates/<int:pk>", tv.InvoiceTemplateDetailView.as_view()),
    path("platform/tenants/<int:tenant_id>/support-license", v.PilotSupportLicenseView.as_view()),
    path("client-space/profiles", v.ProfilesView.as_view()),
    path("platform/tenants/<int:tenant_id>/client-space-profiles", v.PilotProfilesView.as_view()),
]
