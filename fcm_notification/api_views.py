import json
import logging
from datetime import datetime

from django.db import transaction
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from fcm_notification.models import PushMessage
from fcm_notification.serializers import (
    FcmTokenSerializer, PushMessageImageSerializer, PushMessageSerializer, MSG_TYPE_SERIALIZER_MAP
)
from fcm_notification.services.notification_service import PushSender, send_push_message

logger = logging.getLogger('dotai')


def get_current_date_time():
    now = datetime.now()
    return now.strftime("%d-%b-%y %H:%M:%S")


class RegisterFcmTokenAPI(APIView):
    authentication_classes = (BasicAuthentication,)
    permission_classes = (IsAuthenticated,)
    api_name = 'register_fcm_token'

    def post(self, request):
        start_time = datetime.now()
        serializer = FcmTokenSerializer(data=request.data)
        if serializer.is_valid():
            fcm_token = serializer.save(serializer.validated_data)
            return Response(FcmTokenSerializer(instance=fcm_token).data)
        else:
            logger.error("%s API failed. errors: %s" % (self.api_name, json.dumps(serializer.errors)))
            response_time = (datetime.now() - start_time).total_seconds()
            return Response(data=serializer.errors, status=HTTP_400_BAD_REQUEST)


class PushMessageImageAPI(APIView):
    authentication_classes = (SessionAuthentication,)

    def post(self, request):
        serializer = PushMessageImageSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            serializer.save()
            return Response(serializer.data)


class PushMessageAPI(APIView):
    authentication_classes = (SessionAuthentication, BasicAuthentication,)

    def get(self, request, id):
        try:
            push_sender = PushSender(id, None)
        except PushMessage.DoesNotExist:
            raise NotFound()
        return Response(push_sender.create_push_body(push_sender.push_message))

    @transaction.atomic
    def post(self, request):
        serializer = PushMessageSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            message_type = serializer.validated_data['type']
            if message_type != 'INFO':
                action_serializer_class = MSG_TYPE_SERIALIZER_MAP.get(message_type)
                action_serializer = action_serializer_class(data=request.data.get('action'))
                if action_serializer.is_valid():
                    push_message = serializer.save()
                    action_serializer.save(push_message=push_message)
                else:
                    return Response(action_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            else:
                serializer.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)


class SendPushMessageAPIView(APIView):
    def post(self, request, message_id, mobile_no):
        success, failed = send_push_message(message_id, mobile_no, request.user.username)
        return Response({"message": "Notification sent to %s devices" % success})
