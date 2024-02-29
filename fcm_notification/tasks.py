import re
import socket
from string import Template

from celery import shared_task
from celery.utils.log import get_task_logger
from django.core.paginator import Paginator
from django.db import connection
from firebase_admin.exceptions import FirebaseError

from fcm_notification import settings
from fcm_notification.models import (
    BulkNotificationFile, BulkNotificationReceiver, BulkNotificationSchedule, BulkNotificationSendRequest, ReceiverType,
    FcmToken, AppInstallStatus, UninstallTracking, MessageCategory
)
from fcm_notification.services.notification_service import PushSender
from fcm_notification.utilities.validators import VALID_MOBILE_REGEX

logger = get_task_logger(__name__)
mobile_regex = re.compile(VALID_MOBILE_REGEX)
mobile_column = 'mobile'


@shared_task(name='notification.parse_bulk_notification_file')
def parse_bulk_notification_file(file_id):
    bulk_notification_file = BulkNotificationFile.objects.select_related('request').get(pk=file_id)
    bulk_notification_request = bulk_notification_file.request

    file_rows = []
    file_path = bulk_notification_file.uploaded_file.path
    for row_dict in PushSender.read_next_file_row(file_path):
        row_dict = _remove_space_from_dict(row_dict)
        number = row_dict.get(mobile_column, None)
        if number and not number.startswith('0'):
            number = '0{}'.format(number)
        if number and mobile_regex.match(number):
            row_dict[mobile_column] = number
            file_rows.append(row_dict)

    logger.info('Number of valid mobile number: %s', len(file_rows))
    # Overwrite file with valid receiver mobile number
    PushSender.write_to_file(file_path, file_rows)

    bulk_notification_request.status = 2  # 2 <> READY
    bulk_notification_request.receiver_count = len(file_rows)
    bulk_notification_request.save()
    # Add receiver list to receiver table asynchronously
    add_receiver_mobile_to_db.delay(file_id)


@shared_task(name='notification.add_receiver_mobile_to_db')
def add_receiver_mobile_to_db(file_id):
    bulk_notification_file = BulkNotificationFile.objects.select_related('request').get(pk=file_id)
    bulk_notification_request = bulk_notification_file.request

    receiver_mobiles = []
    for row_dict in PushSender.read_next_file_row(bulk_notification_file.uploaded_file.path):
        number = row_dict.get(mobile_column, None)
        if number and mobile_regex.match(number):
            receiver_mobiles.append(number)

    receivers = [BulkNotificationReceiver(request=bulk_notification_request, mobile=mobile)
                 for mobile in receiver_mobiles]
    BulkNotificationReceiver.objects.bulk_create(receivers)


@shared_task(name='notification.send_periodic_bulk_notification')
def send_periodic_bulk_notification(schedule_id):
    schedule = BulkNotificationSchedule.objects.select_related("request__message").get(pk=schedule_id)
    bulk_request = schedule.request
    send_request = BulkNotificationSendRequest(
        request_id=bulk_request.id, receiver_count=bulk_request.receiver_count,
        created_by=schedule.scheduled_by, chunk_delay=0)
    send_request.status = 2  # PROCESSING
    send_request.save()
    send_bulk_notification.delay(send_request.id)


@shared_task(name='notification.send_bulk_notification')
def send_bulk_notification(send_request_id):
    logger.info("Sending bulk notification for send_request_id: %s", send_request_id)
    send_request = BulkNotificationSendRequest.objects.select_related('request__message').get(pk=send_request_id)
    notification_request = send_request.request
    if notification_request.receiver_type == ReceiverType.FILE.name:
        paginator = _create_message_paginator_for_file(notification_request)
    else:
        paginator = _create_message_paginator_for_tg(notification_request)
        send_request.receiver_count = _count_receiver_for_tg(notification_request)

    logger.info("Sending bulk notification to %s users, total_page: %s", paginator.count, paginator.num_pages)
    send_request.chunk_size = settings.BULK_NOTIFICATION_CHUNK_SIZE
    send_request.total_chunk = paginator.num_pages
    send_request.message = notification_request.message
    send_request.active_user_count = paginator.count
    send_request.status = 5
    send_request.save()

    total_success, total_fail = _send_message_paginator(send_request_id, paginator)

    send_request.status = 3  # COMPLETE
    send_request.total_success = total_success
    send_request.total_fail = total_fail
    send_request.save()
    logger.info('Bulk notification with send_request_id: %s completed', send_request_id)


@shared_task(name='notification.track_app_uninstall')
def track_app_uninstall():
    tokens_query = FcmToken.objects.filter(app_status=AppInstallStatus.ACTIVE.name).order_by("id")
    paginator = Paginator(tokens_query, settings.BULK_NOTIFICATION_CHUNK_SIZE)
    installed = uninstalled = failed = 0
    logger.info("Checking app uninstall for %s user, total chunk: %s", paginator.count, paginator.num_pages)
    message_payload = PushSender.create_uninstall_tracking_message()
    total_uninstalled_tokens = []
    for idx in paginator.page_range:
        tokens = paginator.page(idx).object_list
        logger.info("Sending uninstall tracking chunk: %s, total tokens: %s", idx, len(tokens))
        # noinspection PyBroadException
        try:
            fcm_tokens = [token.token for token in tokens]
            batch_response = PushSender.send_multicast_message(message_payload, fcm_tokens)
            uninstalled_tokens = PushSender.get_uninstalled_tokens(tokens, batch_response)
            for uninstalled_token in uninstalled_tokens:
                uninstalled_token.app_status = AppInstallStatus.UNINSTALLED.name
                total_uninstalled_tokens.append(uninstalled_token)
            installed += batch_response.success_count
            uninstalled += len(uninstalled_tokens)
            failed += len(tokens) - (batch_response.success_count + len(uninstalled_tokens))
        except Exception:
            logger.exception("Error sending uninstall tracking notification")
            failed += len(tokens)

    logger.info("Updating %s fcm token status to UNINSTALLED", len(total_uninstalled_tokens))
    FcmToken.objects.bulk_update(total_uninstalled_tokens, ["app_status"], 5000)

    total_checked = installed + uninstalled + failed
    logger.info("Total device check: %s, installed found: %s, uninstalled: %s, error: %s", total_checked, installed, uninstalled, failed)
    UninstallTracking.objects.create(
        total_checked=total_checked,
        installed_found=installed,
        uninstalled_found=uninstalled,
        failed_count=failed
    )


def _create_message_paginator_for_file(notification_request):
    push_body_dict = PushSender.create_push_body(notification_request.message)
    bulk_file = BulkNotificationFile.objects.get(request=notification_request)
    number_map = {}
    numbers = set()
    for row_dict in PushSender.read_next_file_row(bulk_file.uploaded_file.path):
        mobile = row_dict[mobile_column]
        number_map[mobile] = row_dict
        numbers.add(mobile)

    fcm_token_dict = _get_fcm_token_dict(numbers)
    messages = []
    for number, fcm_token in fcm_token_dict.items():
        if notification_request.message.category == MessageCategory.CUSTOM.name:
            payload = _format_push_body(push_body_dict, number_map[number])
        else:
            payload = push_body_dict

        if PushSender.is_valid_message_payload(payload):
            fcm_message = PushSender.create_fcm_message(payload, fcm_token)
            messages.append(fcm_message)
        else:
            logger.warn("Invalid notification payload for mobile: %s", number)

    paginator = Paginator(messages, settings.BULK_NOTIFICATION_CHUNK_SIZE)
    return paginator


def _get_fcm_token_dict(numbers: set):
    numbers = list(numbers)
    fcm_token_dict = {}
    paginator = Paginator(numbers, 5000)
    for idx in paginator.page_range:
        page = paginator.page(idx)
        number_chunk = [number for number in page.object_list]
        raw_query = """
            SELECT DISTINCT fcm.device_id, fcm.id, fcm.token, fcm.app_version_number, fcm.created_at, fcm.updated_at, ru.mobile
            FROM notification_fcmtoken fcm
            INNER JOIN registered_users ru ON fcm.device_id = ru.device_id
            WHERE fcm.app_status='ACTIVE' AND ru.device_status = 'active' AND ru.mobile IN ('{}')
        """
        raw_query = raw_query.format("','".join(number_chunk))
        device_data = FcmToken.objects.raw(raw_query)
        if device_data and len(device_data) > 0:
            for device in device_data:
                fcm_token_dict[device.mobile] = device.token

    return fcm_token_dict


def _format_push_body(push_dict: dict, data_dict: dict):
    formatted_dict = {}
    data_plain_dict = dict(data_dict)  # data_dict is a ordered dict, so convert into normal dict
    for key, value in push_dict.items():
        template = Template(value)
        formatted_dict[key] = template.safe_substitute(data_plain_dict)

    return formatted_dict


def _create_message_paginator_for_tg(notification_request):
    raw_sql_query = """
        SELECT DISTINCT fcm.device_id, fcm.id, fcm.token, fcm.app_version_number, fcm.created_at, fcm.updated_at
        FROM notification_fcmtoken fcm
        INNER JOIN registered_users ru ON fcm.device_id = ru.device_id
        INNER JOIN register_dotaiuser tu ON ru.dotai_user_id = tu.id
        INNER JOIN register_dotaiuser_tag_list tutl ON tu.id = tutl.dotaiuser_id
        INNER JOIN register_tag tag ON tutl.tag_id = tag.id
        INNER JOIN notification_bulknotificationrequest_receiving_tags nrt ON tag.id = nrt.tag_id
        INNER JOIN notification_bulknotificationrequest bnr ON nrt.bulknotificationrequest_id = bnr.id
        WHERE fcm.app_status='ACTIVE' AND ru.device_status='active' AND bnr.id=%s
    """
    device_data = FcmToken.objects.raw(raw_sql_query, [notification_request.id])
    messages = []
    if device_data and len(device_data) > 0:
        payload = PushSender.create_push_body(notification_request.message)
        if PushSender.is_valid_message_payload(payload):
            for device in device_data:
                fcm_message = PushSender.create_fcm_message(payload, device.token)
                messages.append(fcm_message)
        else:
            logger.warn("Invalid notification payload")

    paginator = Paginator(messages, settings.BULK_NOTIFICATION_CHUNK_SIZE)
    return paginator


def _count_receiver_for_tg(notification_request):
    with connection.cursor() as cursor:
        raw_sql_query = """
            SELECT count(DISTINCT tu.mobile_no)
            FROM register_dotaiuser tu
            INNER JOIN register_dotaiuser_tag_list tutl ON tu.id = tutl.dotaiuser_id
            INNER JOIN register_tag tag ON tutl.tag_id = tag.id
            INNER JOIN notification_bulknotificationrequest_receiving_tags nrt ON tag.id = nrt.tag_id
            INNER JOIN notification_bulknotificationrequest bnr ON nrt.bulknotificationrequest_id = bnr.id
            WHERE bnr.id=%s
        """
        cursor.execute(raw_sql_query, [notification_request.id])
        row = cursor.fetchone()
        return row[0]


def _send_message_paginator(send_request_id, paginator: Paginator):
    """
    Send every chunk from paginator. If failed to send any chunk, then it will add to failed list.
    This failed will will retry immediately. This process will repeat configured times
    :param send_request_id: Bulk notification send request ID
    :param paginator: Constructed firebase message paginator
    """
    total_success = 0
    total_fail = 0
    retry_count = settings.BULK_NOTIFICATION_CHUNK_MAX_RETRIES
    while retry_count > 0:
        failed_messages = []
        for idx in paginator.page_range:
            logger.info("Sending bulk message for send_request_id: %s, chunk: %s", send_request_id, idx)
            try:
                success, fail = _send_message_chunk(send_request_id, paginator.page(idx))
                total_success += success
                total_fail += fail
            except(FirebaseError, socket.timeout):
                logger.exception("Error calling firebase. Chunk will retry for send_request_id: %s", send_request_id)
                failed_messages += [message for message in paginator.page(idx).object_list]

        if len(failed_messages) == 0:
            # No failed message anymore, so no need to retry
            retry_count = 0
        else:
            paginator = Paginator(failed_messages, settings.BULK_NOTIFICATION_CHUNK_SIZE)
            retry_count -= 1
            if retry_count == 0:
                logger.error("Unable to send %s messages for send_request_id: %s", len(failed_messages), send_request_id)
                total_fail += len(failed_messages)

    return total_success, total_fail


def _send_message_chunk(send_request_id, page):
    messages = [message for message in page.object_list]
    # noinspection PyBroadException
    try:
        success, fail = PushSender.send_all_message(messages)
        return success, len(messages) - success
    except(FirebaseError, socket.timeout) as exc:
        raise exc
    except Exception:
        logger.exception("Chunk failed for send_request_id: %s, total_user: %s", send_request_id, len(messages))
        return 0, len(messages)


def _remove_space_from_dict(data_dict: dict):
    clean_dic = {}
    for key, value in data_dict.items():
        key = str(key).strip()
        value = str(value).strip()
        clean_dic[key] = value

    return clean_dic
