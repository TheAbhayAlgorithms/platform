from django.urls import path
from polls import views

app_name = 'polls'

urlpatterns = [
    # Staff Polls & Elections Management
    path('', views.poll_list, name='poll_list'),
    path('new/', views.poll_create, name='poll_create'),
    path('<int:poll_id>/', views.poll_detail, name='poll_detail'),
    path('<int:poll_id>/edit/', views.poll_edit, name='poll_edit'),
    path('<int:poll_id>/close/', views.poll_close, name='poll_close'),
    path('<int:poll_id>/options/add/', views.poll_option_add, name='poll_option_add'),
    path('<int:poll_id>/export/', views.poll_export_csv, name='poll_export_csv'),

    # Staff Feedback Management
    path('feedback/', views.feedback_list, name='feedback_list'),
    path('feedback/<int:feedback_id>/', views.feedback_detail, name='feedback_detail'),
    path('feedback/<int:feedback_id>/respond/', views.feedback_respond, name='feedback_respond'),

    # Member Portal routes
    path('portal/', views.portal_polls_list, name='portal_polls'),
    path('portal/<int:poll_id>/vote/', views.portal_poll_vote, name='portal_vote'),
    path('portal/feedback/', views.portal_feedback_view, name='portal_feedback'),
]
