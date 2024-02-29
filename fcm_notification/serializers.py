from datetime import datetime

from rest_framework import serializers
import pytz

from fcm_notification.models import (
    FcmToken, AppInstallStatus, LinkMessage, ImageRequestMessage, FileRequestMessage, PopupMessage, PushMessage,
    PushMessageImage, FileTypeRequest, BulkScheduleType
)


class FormattedNumberField(serializers.FloatField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.replace(",", "")
        return super(FormattedNumberField, self).to_internal_value(data)


class FcmTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = FcmToken
        fields = ['device_id', 'token', 'app_version_number']
        extra_kwargs = {
            'device_id': {'validators': []},
        }

    def save(self, validated_data):
        device_id = validated_data.pop('device_id')
        validated_data['app_status'] = AppInstallStatus.ACTIVE.name
        fcm_token, created = FcmToken.objects.update_or_create(device_id=device_id, defaults=validated_data)
        return fcm_token


class PushMessageSerializer(serializers.ModelSerializer):
    thumbnail_img = serializers.SerializerMethodField(read_only=True)
    full_img = serializers.SerializerMethodField(read_only=True)
    action = serializers.SerializerMethodField(read_only=True)
    created_at = serializers.SerializerMethodField(read_only=True)

    def get_thumbnail_img(self, obj):
        if obj.image is not None and obj.image.thumbnail_img:
            return obj.image.thumbnail_img.url
        return None

    def get_full_img(self, obj):
        if obj.image is not None and obj.image.full_img:
            return obj.image.full_img.url
        return None

    def get_action(self, obj):
        if obj.type == 'LINK':
            instance = LinkMessage.objects.get(push_message=obj)
        elif obj.type == 'IMAGE_UPLOAD':
            instance = ImageRequestMessage.objects.get(push_message=obj)
        elif obj.type == 'FILE_UPLOAD':
            instance = FileRequestMessage.objects.get(push_message=obj)
        elif obj.type == 'POPUP_MESSAGE':
            instance = PopupMessage.objects.get(push_message=obj)
            # TODO: For AI-748 temporary set min_delay = 100 years. Should remove this in future
            instance.min_delay = 3153600000
        else:
            return None
        return MSG_TYPE_SERIALIZER_MAP[obj.type](instance).data

    def get_created_at(self, obj):
        # created_at in obj is in gmt+6. We need to convert it to gmt as per APP's requirement
        return obj.created_at.astimezone(pytz.utc)

    class Meta:
        model = PushMessage
        fields = '__all__'
        extra_kwargs = {'image': {'write_only': True}}


class PushMessageImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushMessageImage
        fields = '__all__'

    def validate(self, attrs):
        if not attrs.get('thumbnail_img') and not attrs.get('full_img'):
            raise serializers.ValidationError("At least one image must be provided")

        return attrs


class LinkMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = LinkMessage
        exclude = ('push_message',)


class ImageRequestMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageRequestMessage
        exclude = ('push_message',)


class FileTypeRequestSerializer(serializers.ModelSerializer):
    # file_type_id = serializers.CharField(read_only=True)

    class Meta:
        model = FileTypeRequest
        exclude = ('file_request_message',)
        # extra_kwargs = {'file_type': {'write_only': True}}


class FileRequestMessageSerializer(serializers.ModelSerializer):
    files = FileTypeRequestSerializer(many=True, source='file_type_request_set', allow_empty=False)

    class Meta:
        model = FileRequestMessage
        exclude = ('push_message',)

    def create(self, validated_data):
        requested_files = validated_data.pop('file_type_request_set')
        file_request_message = FileRequestMessage.objects.create(**validated_data)

        for file_request in requested_files:
            FileTypeRequest.objects.create(file_request_message=file_request_message, **file_request)

        return file_request_message


class PopupMessageSerializer(serializers.ModelSerializer):
    sent_at = serializers.SerializerMethodField(read_only=True)

    def get_sent_at(self, obj):
        return datetime.now()

    class Meta:
        model = PopupMessage
        exclude = ('push_message',)


MSG_TYPE_SERIALIZER_MAP = {
    'LINK': LinkMessageSerializer,
    'IMAGE_UPLOAD': ImageRequestMessageSerializer,
    'FILE_UPLOAD': FileRequestMessageSerializer,
    'POPUP_MESSAGE': PopupMessageSerializer
}


class SendBulkNotificationSerializer(serializers.Serializer):
    schedule_type = serializers.CharField(required=True, max_length=20)
    onetime_send_date = serializers.DateTimeField(required=False, allow_null=True)
    weekly_days = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True, allow_null=True)
    monthly_days = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True, allow_null=True)
    should_repeat = serializers.BooleanField(required=False, default=False)
    schedule_time = serializers.TimeField(required=False, allow_null=True)
    repeat_until = serializers.DateField(required=False, allow_null=True)
    chunk_delay = serializers.IntegerField(required=False, default=0)

    # noinspection PyMethodMayBeStatic
    def validate_schedule_type(self, value):
        if value not in [e for e in BulkScheduleType.names]:
            raise serializers.ValidationError("Invalid schedule type")
        return value

    def validate(self, attrs):
        schedule_type = attrs['schedule_type']
        if schedule_type == BulkScheduleType.WEEKLY.name:
            days = attrs.get('weekly_days', None)
            if days is None or len(days) == 0:
                raise serializers.ValidationError({'weekly_days': 'weekly_days should not be empty'})
        if schedule_type == BulkScheduleType.MONTHLY.name:
            days = attrs.get('monthly_days', None)
            if days is None or len(days) == 0:
                raise serializers.ValidationError({'monthly_days': 'monthly_days should not be empty'})
        if schedule_type in [BulkScheduleType.WEEKLY.name, BulkScheduleType.MONTHLY.name]:
            if attrs.get('should_repeat', False) and attrs.get('repeat_until', None) is None:
                raise serializers.ValidationError({'repeat_until': 'repeat_until should not be null'})
            if attrs.get('schedule_time', None) is None:
                raise serializers.ValidationError({'schedule_time': 'schedule_time should not be null'})
        return attrs

    def create(self, validated_data):
        return validated_data

    def update(self, instance, validated_data):
        return validated_data
