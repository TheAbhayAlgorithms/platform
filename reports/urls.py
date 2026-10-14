from django.urls import path
from reports import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_hub, name='hub'),
    path('daily-collection/', views.daily_collection_report, name='daily_collection'),
    path('revenue-summary/', views.revenue_summary_report, name='revenue_summary'),
    path('defaulters/', views.defaulters_report, name='defaulters'),
    path('demographics/', views.member_demographics_report, name='demographics'),
]
