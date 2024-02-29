import csv
import json
import logging
from datetime import datetime

import pytz
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from firebase_admin.messaging import UnregisteredError

from fcm_notification.fcm_client import FCMClient
from fcm_notification.models import PushMessage, FcmToken, MessageDeliveryLog
from fcm_notification.serializers import PushMessageSerializer

logger = logging.getLogger('dotai')
fcm_client = FCMClient()


def send_push_message(message_id, mobile_no, sender_name):
    try:
        push_sender = PushSender(message_id, sender_name)
    except PushMessage.DoesNotExist:
        raise Http404("Message does not exist")
    return push_sender.send_push_to_mobile(mobile_no)


class RegisteredUser:
    pass


class PushSender:
    def __init__(self, message_id, sender_name):
        self.message_id = message_id
        self.sender_name = sender_name
        self.push_message = PushMessage.objects.select_related('image').get(pk=message_id)
        self.message_payload = PushSender.create_push_body(self.push_message)

    def send_push_to_mobile(self, mobile_no):
        device_ids = RegisteredUser.objects.filter(mobile=mobile_no, device_status='active').values_list('device_id')
        success_count = 0

        for device_id_tuple in device_ids:
            device_id = device_id_tuple[0]
            try:
                fcm_token = FcmToken.objects.get(device_id=device_id)
            except FcmToken.DoesNotExist:
                fcm_token = None

            if fcm_token is None:
                return 0, 1

            # noinspection PyBroadException
            try:
                fcm_client.send_message(self.message_payload, fcm_token.token)
                MessageDeliveryLog.objects.create(
                    message=self.push_message, mobile=mobile_no, device_id=device_id,
                    created_by=self.sender_name
                )
                success_count += 1
            except Exception:
                logger.exception("failed to send push message")
        return success_count, 1 - success_count

    @staticmethod
    def send_multicast_message(message_payload, fcm_tokens):
        return fcm_client.send_multicast_message(message_payload, fcm_tokens)

    @staticmethod
    def send_all_message(messages):
        batch_response = fcm_client.send_all_message(messages)
        return batch_response.success_count, batch_response.failure_count

    @staticmethod
    def create_push_body(push_message):
        serializer_data = PushMessageSerializer(push_message).data
        serializer_data.pop('title')
        serializer_data.pop('body')

        payload = {
            'title': push_message.title,
            'body': push_message.body,
            'data': json.dumps(serializer_data, cls=DjangoJSONEncoder)
        }
        if push_message.type == 'POPUP_MESSAGE':
            payload['eventName'] = 'AI_POPUP_MESSAGE'
            payload['eventType'] = 'POPUP_MESSAGE'
        else:
            payload['eventName'] = 'AI_INBOX_MESSAGE'
            payload['eventType'] = 'INBOX_MESSAGE'

        return payload

    @staticmethod
    def read_next_file_row(file_path: str) -> dict:
        with open(file_path, newline='') as csv_file:
            csv_reader = csv.DictReader(csv_file, resaiey='non_key_values')
            for row in csv_reader:
                yield row

    @staticmethod
    def write_to_file(file_path: str, file_rows: list):
        if len(file_rows) == 0:
            return
        with open(file_path, 'w', newline='') as csv_file:
            fieldnames = list(file_rows[0].keys())
            csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            csv_writer.writeheader()
            for row in file_rows:
                csv_writer.writerow(row)

    @staticmethod
    def create_fcm_message(push_body, fcm_token):
        fcm_message = fcm_client.create_message(push_body, fcm_token)
        return fcm_message

    @staticmethod
    def is_valid_message_payload(payload):
        payload_str = json.dumps(payload, cls=DjangoJSONEncoder)
        # To get actual size in bytes (not length) of the payload, we need to encode it into utf-8
        payload_length = len(payload_str.encode('utf-8'))
        return payload_length < 4000

    @staticmethod
    def create_uninstall_tracking_message():
        push_body = {
            "eventName": "AI_UNINSTALL_TRACKING",
            "eventType": "UNINSTALL_TRACKING",
            "eventTime": datetime.now(tz=pytz.utc).isoformat()
        }
        return push_body

    @staticmethod
    def get_uninstalled_tokens(tokens, batch_response):
        responses = batch_response.responses
        uninstalled_devices = []
        for idx, resp in enumerate(responses):
            if type(resp.exception) == UnregisteredError:
                uninstalled_devices.append(tokens[idx])
        return uninstalled_devices
