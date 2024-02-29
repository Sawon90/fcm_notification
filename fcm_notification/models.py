import uuid
from argparse import FileType

from django.core.validators import MinLengthValidator, MinValueValidator, URLValidator
from django.db import models
from django.forms.fields import URLField as FormURLField
from django_celery_beat.models import PeriodicTask

from fcm_notification.utilities.common_services import image_upload_path, notification_number_file_upload_path
from fcm_notification.utilities.validators import validate_file_size

MESSAGE_TYPES = (
    ('INFO', 'INFO'), 
    ('FILE_UPLOAD', 'FILE_UPLOAD'), 
    ('IMAGE_UPLOAD', 'IMAGE_UPLOAD'), 
    ('LINK', 'LINK'),
    ('POPUP_MESSAGE', 'POPUP_MESSAGE'),
)


class MessageCategory(models.TextChoices):
    GENERIC = 'GENERIC'
    CUSTOM = 'CUSTOM'


IMAGE_RESOLUTION_TYPES = (
    ('LOW', 'LOW'),
    ('MEDIUM', 'MEDIUM'),
    ('HIGH', 'HIGH'),
)

MSG_CONTENT_TYPE = (
    ('text', 'TEXT'),
    ('html', 'HTML'),
)

BULK_NOTIFICATION_STATUS = (
    (1, 'PROCESSING'),
    (2, 'READY'),
)

BULK_NOTIFICATION_SEND_STATUS = (
    (1, 'SCHEDULED'),
    (2, 'PROCESSING'),
    (3, 'COMPLETE'),
    (4, 'CANCELED'),
    (5, 'IN_PROGRESS'),
)


class ReceiverType(models.TextChoices):
    FILE = 'FILE'
    TG = 'TG'


class BulkScheduleType(models.TextChoices):
    ONE_TIME = 'ONE_TIME'
    WEEKLY = 'WEEKLY'
    MONTHLY = 'MONTHLY'


class AppInstallStatus(models.TextChoices):
    ACTIVE = 'ACTIVE'
    UNINSTALLED = 'UNINSTALLED'


class AiURLFormField(FormURLField):
    default_validators = [URLValidator(
        schemes=['http', 'https', 'ftp', 'ftps', 'external-http', 'external-https'])]


class AiURLField(models.CharField):
    default_validators = [URLValidator(
        schemes=['http', 'https', 'ftp', 'ftps', 'external-http', 'external-https'])]
    description = "URL"

    def __init__(self, verbose_name=None, name=None, **kwargs):
        kwargs.setdefault('max_length', 200)
        super().__init__(verbose_name, name, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 200:
            del kwargs['max_length']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        return super().formfield(**{
            'form_class': AiURLFormField,
            **kwargs,
        })


class FcmToken(models.Model):
    device_id = models.CharField(max_length=50, unique=True)
    token = models.CharField(max_length=255)
    app_version_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    app_status = models.CharField(
        max_length=15, null=False, blank=False, default=AppInstallStatus.ACTIVE.name,
        choices=AppInstallStatus.choices
    )

    class Meta:
        indexes = [
            models.Index(fields=['app_status'])
        ]

    def __str__(self):
        return self.device_id


class ImageRequest(models.Model):
    file_type = models.ForeignKey(FileType, on_delete=models.CASCADE)
    description = models.CharField(max_length=250, blank=True, null=True)
    resolution = models.CharField(choices=IMAGE_RESOLUTION_TYPES, max_length=8)
    is_live = models.BooleanField(default=False)

    class Meta:
        abstract = True


class ActionMessage(models.Model):
    title = models.CharField(max_length=100)

    def __str__(self):
        return str(self.title)

    class Meta:
        abstract = True


class PushMessageImage(models.Model):
    thumbnail_img = models.ImageField(null=True, upload_to=image_upload_path, validators=[validate_file_size])
    full_img = models.ImageField(null=True, upload_to=image_upload_path, validators=[validate_file_size])


class PushMessage(models.Model):
    title = models.CharField(max_length=60)
    summary = models.CharField(max_length=250)
    body = models.CharField(max_length=5000)
    content_type = models.CharField(max_length=4, choices=MSG_CONTENT_TYPE, default='text')
    created_at = models.DateTimeField(auto_now_add=True)
    type = models.CharField(choices=MESSAGE_TYPES, max_length=20)
    image = models.ForeignKey(PushMessageImage, on_delete=models.SET_NULL, null=True, blank=True)
    category = models.CharField(choices=MessageCategory.choices, max_length=15)

    def __str__(self):
        return "{} - {}".format(self.id, self.title)


class FileRequestMessage(ActionMessage):
    push_message = models.OneToOneField(PushMessage, on_delete=models.CASCADE)


class FileTypeRequest(ImageRequest):
    title = models.CharField(max_length=100)
    file_request_message = models.ForeignKey(FileRequestMessage, on_delete=models.CASCADE, related_name='file_type_request_set')


class ImageRequestMessage(ImageRequest, ActionMessage):
    push_message = models.OneToOneField(PushMessage, on_delete=models.CASCADE)
    min_files = models.PositiveSmallIntegerField()
    max_files = models.PositiveSmallIntegerField()


class LinkMessage(ActionMessage):
    push_message = models.OneToOneField(PushMessage, on_delete=models.CASCADE)
    link_url = AiURLField()


class PopupMessage(models.Model):
    push_message = models.OneToOneField(PushMessage, on_delete=models.CASCADE)
    button_text = models.CharField(max_length=50, null=False, blank=False)
    display_type = models.CharField(max_length=25, null=False, blank=False, choices=(
        ('COMPLETE_MESSAGE', 'COMPLETE_MESSAGE'),
        ('IMAGE_MESSAGE', 'IMAGE_MESSAGE'),
    ))
    action_type = models.CharField(max_length=25, null=False, blank=False, choices=(
        ('OPEN_URL', 'OPEN_URL'),
        ('OPEN_ACTIVITY', 'OPEN_ACTIVITY'),
        ('DISMISS', 'DISMISS'),
    ))
    action_data = models.CharField(max_length=200, null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    min_delay = models.IntegerField(null=True, blank=True, default=0)


class MessageDeliveryLog(models.Model):
    message = models.ForeignKey(PushMessage, on_delete=models.CASCADE)
    mobile = models.CharField(max_length=11, db_index=True)
    device_id = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=150)


class EventNotification(models.Model):
    event = models.PositiveSmallIntegerField(choices=EVENTS, unique=True)
    message = models.ForeignKey(PushMessage, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class BulkNotificationRequest(models.Model):
    message = models.ForeignKey(PushMessage, on_delete=models.CASCADE)
    title = models.CharField(max_length=1000, null=True, blank=True)
    status = models.PositiveSmallIntegerField(choices=BULK_NOTIFICATION_STATUS, default=1)
    receiver_count = models.IntegerField(null=False, default=0)
    created_by = models.CharField(max_length=150, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    receiver_type = models.CharField(max_length=15, null=False, blank=False, choices=ReceiverType.choices)

    class Meta:
        indexes = [
            models.Index(fields=['receiver_type'])
        ]

    def __str__(self):
        return str(self.title)


class BulkNotificationFile(models.Model):
    request = models.ForeignKey(BulkNotificationRequest, on_delete=models.CASCADE)
    uploaded_file = models.FileField(
        null=False,
        max_length=150,
        upload_to=notification_number_file_upload_path
    )
    created_at = models.DateTimeField(auto_now_add=True)


class BulkNotificationReceiver(models.Model):
    request = models.ForeignKey(BulkNotificationRequest, on_delete=models.CASCADE, related_name='receivers')
    mobile = models.CharField(max_length=11, null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['mobile'], name='idx_bulk_notif_receiver_mobile')
        ]

    def __str__(self):
        return self.mobile


class BulkNotificationSendRequest(models.Model):
    request = models.ForeignKey(BulkNotificationRequest, on_delete=models.CASCADE)
    status = models.PositiveSmallIntegerField(choices=BULK_NOTIFICATION_SEND_STATUS, null=False, blank=False)
    receiver_count = models.IntegerField(null=False, blank=False)
    chunk_size = models.IntegerField(null=True, blank=True)
    total_chunk = models.IntegerField(null=True, blank=True)
    created_by = models.CharField(max_length=150, null=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    schedule_time = models.DateTimeField(null=True, blank=True)
    chunk_delay = models.IntegerField(null=False, blank=False, default=0)
    active_user_count = models.IntegerField(null=False, default=0)
    total_success = models.IntegerField(null=False, default=0)
    total_fail = models.IntegerField(null=False, default=0)
    message = models.ForeignKey(PushMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')


class BulkNotificationSendCount(models.Model):
    send_request = models.ForeignKey(BulkNotificationSendRequest, on_delete=models.CASCADE, related_name='send_counts')
    success_count = models.IntegerField(default=0, null=False, blank=False)
    failed_count = models.IntegerField(default=0, null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)


class BulkNotificationSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(BulkNotificationRequest, on_delete=models.CASCADE, related_name='schedules')
    task = models.ForeignKey(PeriodicTask, on_delete=models.CASCADE)
    schedule_type = models.CharField(max_length=15, null=False, blank=False, choices=BulkScheduleType.choices)
    schedule_time = models.TimeField(null=False, blank=False)
    should_repeat = models.BooleanField(null=False, blank=False, default=False)
    repeat_days = models.CharField(null=False, max_length=125)
    repeat_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_by = models.CharField(max_length=150, null=False)


class UninstallTracking(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    total_checked = models.IntegerField(null=False, blank=False)
    installed_found = models.IntegerField(null=False, blank=False)
    uninstalled_found = models.IntegerField(null=False, blank=False)
    failed_count = models.IntegerField(null=False, blank=False)
