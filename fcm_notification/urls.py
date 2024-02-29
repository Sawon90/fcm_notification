from django.urls import path

from fcm_notification.api_views import (
    RegisterFcmTokenAPI, PushMessageAPI, SendPushMessageAPIView, PushMessageImageAPI
)
from fcm_notification.views import (
    create_push_message, PushMessageList, message_details, BulkMessageRequestList,
    create_bulk_message_request, SendBulkMessage, BulkMessageReceiversList, BulkMessageSendRequestView,
    BulkMessageSchedulesView, BulkMessageTagsView, edit_message, send_message, send_message_success
)

urlpatterns = [
    path('message/create', create_push_message, name='create_push_message'),
    path('message', PushMessageList.as_view(), name='push_message_list'),
    path('message/<int:message_id>', message_details, name='message_details'),
    path('message/bulk', BulkMessageRequestList.as_view(), name='bulk_message_list'),
    path('message/bulk/create', create_bulk_message_request, name='create_bulk_message'),
    path('message/bulk/<int:request_id>/send', SendBulkMessage.as_view(), name='send_bulk_message'),
    path('message/bulk/<int:request_id>/receivers', BulkMessageReceiversList.as_view(), name='bulk_message_receivers'),
    path('message/bulk/<int:request_id>/send-request', BulkMessageSendRequestView.as_view(),
         name='bulk_message_send_request'),
    path('message/bulk/<int:request_id>/schedules', BulkMessageSchedulesView.as_view(), name='bulk_message_schedules'),
    path('message/bulk/<int:request_id>/tags', BulkMessageTagsView.as_view(), name='bulk_message_tags'),
    path('message/<int:message_id>/edit', edit_message, name='edit_message'),
    path('message/<int:message_id>/send', send_message, name='send_message'),
    path('message/<int:message_id>/sent', send_message_success, name='message_sent'),
    path('fcm/register', RegisterFcmTokenAPI.as_view(), name='register_fcm_token'),
    path('message', PushMessageAPI.as_view(), name='add_push_message_api'),
    path('message/<int:id>', PushMessageAPI.as_view(), name='get_push_message_api'),
    path('message/<int:message_id>/send/<mobile:mobile_no>', SendPushMessageAPIView.as_view(),
         name='send_push_message_api'),
    path('message/image', PushMessageImageAPI.as_view(), name='push_message_image_api'),
]
