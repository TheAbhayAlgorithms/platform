from django.urls import path
from payments import views

app_name = 'payments'

urlpatterns = [
    path('', views.payment_list_view, name='payment_list'),
    path('record/<int:member_id>/', views.payment_record_view, name='payment_record'),
    path('<int:payment_id>/', views.payment_detail_view, name='payment_detail'),
    path('<int:payment_id>/receipt/pdf/', views.payment_receipt_pdf_view, name='receipt_pdf'),
    path('<int:payment_id>/cancel/', views.payment_cancel_view, name='payment_cancel'),
    path('<int:payment_id>/adjust/', views.payment_adjustment_view, name='payment_adjustment'),
]
