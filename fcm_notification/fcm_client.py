import logging

import firebase_admin
from django.conf import settings
from firebase_admin import credentials
from firebase_admin import messaging

logger = logging.getLogger('dotai')
cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
firebase_admin.initialize_app(cred)


class FCMClient:
    # noinspection PyMethodMayBeStatic
    def create_message(self, message_payload, registration_token):
        message = messaging.Message(
            data=message_payload,
            token=registration_token,
        )
        return message

    # noinspection PyMethodMayBeStatic
    def create_multicast_message(self, payload, fcm_tokens):
        multicast_message = messaging.MulticastMessage(
            tokens=fcm_tokens,
            data=payload
        )
        return multicast_message

    def send_message(self, message_payload, registration_token):
        message = self.create_message(message_payload, registration_token)
        messaging.send(message)

    def send_multicast_message(self, payload, fcm_tokens):
        multicast_message = self.create_multicast_message(payload, fcm_tokens)
        batch_response = messaging.send_multicast(multicast_message)
        return batch_response

    # noinspection PyMethodMayBeStatic
    def send_all_message(self, messages):
        batch_response = messaging.send_all(messages)
        return batch_response
