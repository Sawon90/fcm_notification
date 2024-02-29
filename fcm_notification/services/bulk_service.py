import calendar
import json
import logging
import uuid
from datetime import datetime, timedelta

import pytz
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from fcm_notification.models import (
    BulkNotificationRequest, ReceiverType, BulkScheduleType, BulkNotificationSendRequest, BulkNotificationSchedule
)
from fcm_notification.tasks import send_bulk_notification

logger = logging.getLogger('dotai')


def schedule_bulk_notification(request_id, request_data, sender_name):
    bulk_request = BulkNotificationRequest.objects.select_related("message").get(pk=request_id)
    if bulk_request.receiver_type == ReceiverType.FILE.name and bulk_request.receiver_count <= 0:
        raise Http404('No receiver found for this notification')

    is_scheduled = False
    if request_data['schedule_type'] == BulkScheduleType.ONE_TIME.name:
        send_one_time_notification(bulk_request, request_data, sender_name)
    elif request_data['schedule_type'] in [BulkScheduleType.WEEKLY.name,
                                           BulkScheduleType.MONTHLY.name]:
        schedule_periodic_notification(bulk_request, request_data, sender_name)
        is_scheduled = True
    return is_scheduled


def send_one_time_notification(bulk_request, request_data, sender_name):
    chunk_delay = request_data.get('chunk_delay', 0)
    send_request = BulkNotificationSendRequest(
        request_id=bulk_request.id, receiver_count=bulk_request.receiver_count,
        created_by=sender_name, chunk_delay=chunk_delay)
    schedule_time = request_data.get('onetime_send_date', None)
    if schedule_time:
        schedule_time = schedule_time.replace(tzinfo=pytz.timezone('Asia/Dhaka'))

    # For safety, if scheduled for 30s future, then send notification immediately
    safe_now = datetime.now(tz=pytz.timezone('Asia/Dhaka')) + timedelta(seconds=30)
    if schedule_time is None or schedule_time < safe_now:
        send_request.status = 2  # PROCESSING
        send_request.save()
        send_bulk_notification.delay(send_request.id)
    else:
        send_request.status = 1  # SCHEDULED
        send_request.schedule_time = schedule_time
        send_request.save()
        send_bulk_notification.apply_async(args=[send_request.id], eta=schedule_time)


def schedule_periodic_notification(bulk_request, request_data: dict, sender_name: str):
    uuid_id = uuid.uuid4()
    days = _get_repeat_days(request_data)
    task = PeriodicTask.objects.create(
        crontab=_create_or_get_cron(request_data, days),
        name=str(uuid_id),
        task='notification.send_periodic_bulk_notification',
        args=json.dumps([uuid_id], cls=DjangoJSONEncoder),
        expires=_get_expire_date(request_data)
    )

    schedule = BulkNotificationSchedule()
    schedule.id = uuid_id
    schedule.request = bulk_request
    schedule.task = task
    schedule.schedule_type = request_data['schedule_type']
    schedule.should_repeat = request_data.get('should_repeat', False)
    schedule.schedule_time = request_data.get('schedule_time', None)
    schedule.repeat_until = request_data.get('repeat_until', None)
    schedule.repeat_days = json.dumps(days, cls=DjangoJSONEncoder)
    schedule.scheduled_by = sender_name
    schedule.save()


def _get_repeat_days(request_data: dict):
    days = []
    if request_data['schedule_type'] == BulkScheduleType.WEEKLY.name:
        days = request_data['weekly_days']
    elif request_data['schedule_type'] == BulkScheduleType.MONTHLY.name:
        days = request_data['monthly_days']
    return days


def _create_or_get_cron(request_data: dict, days: list):
    schedule_time = request_data['schedule_time']
    cron = None
    days_str = ",".join(str(d) for d in days)
    if request_data['schedule_type'] == BulkScheduleType.WEEKLY.name:
        cron, _ = CrontabSchedule.objects.get_or_create(
            hour=schedule_time.hour,
            minute=schedule_time.minute,
            day_of_week=days_str,
            timezone=pytz.timezone('Asia/Dhaka')
        )
    elif request_data['schedule_type'] == BulkScheduleType.MONTHLY.name:
        cron, _ = CrontabSchedule.objects.get_or_create(
            hour=schedule_time.hour,
            minute=schedule_time.minute,
            day_of_month=days_str,
            timezone=pytz.timezone('Asia/Dhaka')
        )
    return cron


def _get_expire_date(request_data: dict):
    if request_data.get("should_repeat", False):
        return request_data["repeat_until"]
    schedule_type = request_data["schedule_type"]
    today = datetime.today()
    if schedule_type == BulkScheduleType.MONTHLY.name:
        month_range = calendar.monthrange(today.year, today.month)
        return datetime(today.year, today.month, month_range[1], 23, 59, 59, tzinfo=pytz.timezone('Asia/Dhaka'))
    else:
        week_days = today.weekday()  # Monday is 0 and Sunday is 6
        if week_days < 6:  # We need week from Sunday to Saturday
            week_days = 5 - week_days
        expire_at = today + timedelta(days=week_days)
        return datetime(expire_at.year, expire_at.month, expire_at.day, 23, 59, 59, tzinfo=pytz.timezone('Asia/Dhaka'))
