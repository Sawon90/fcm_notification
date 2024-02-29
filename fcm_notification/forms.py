from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from fcm_notification.models import MESSAGE_TYPES, FcmToken, PushMessage, BulkNotificationRequest
from fcm_notification.utilities.validators import MOBILE_REGEX

MESSAGE_TYPE_FILTERS = (('', '-- all --'),) + MESSAGE_TYPES


class SendPushMessageForm(forms.Form):
    mobile = forms.RegexField(regex=MOBILE_REGEX, required=True, widget=forms.TextInput(attrs={'class':'form-control', 'minlength': 11, 'maxlength': 11}))

    def clean_mobile(self):
        mobile_no = self.cleaned_data['mobile']
        if mobile_no:
            device_ids = RegisteredUser.objects.filter(mobile=mobile_no, device_status='active').values_list('device_id')
            if len(device_ids) == 0:
                raise ValidationError("No active device found with this mobile")

            device_id_list = [x[0] for x in device_ids]
            fcm_toke_count = FcmToken.objects.filter(device_id__in=device_id_list).count()
            if fcm_toke_count == 0:
                raise ValidationError("No active device of this mobile is registered to Firebase")
        
        return mobile_no


class SearchMessageForm(forms.Form):
    title = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control mx-2'}))
    type = forms.ChoiceField(required=False, choices=MESSAGE_TYPE_FILTERS, widget=forms.Select(attrs={'class': 'form-control mx-2'}))


class SearchBulkMessageForm(forms.Form):
    title = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control mx-2'}))


class SearchBulkMessageReceiverForm(forms.Form):
    mobile = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control mx-2', 'minlength': '11', 'maxlength': '11'}))


class EditMessageForm(forms.ModelForm):
    class Meta:
        model = PushMessage
        fields = ('title', 'summary', 'body', )


class GetPromoForm(forms.Form):
    app_version = forms.IntegerField(min_value=1, max_value=2147483647, required=True)


class CreateBulkMessageForm(forms.ModelForm):
    receiver_list = forms.FileField(
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': ".csv"}),
        validators=[FileExtensionValidator(allowed_extensions=['csv'], message='Only csv file is allowed')]
    )

    class Meta:
        model = BulkNotificationRequest
        exclude = ('created_by', 'status', 'receiver_count')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'message': forms.Select(attrs={'class': 'form-control'}),
        }


class CreateTgNotificationForm(forms.ModelForm):
    class Meta:
        model = BulkNotificationRequest
        exclude = ('created_by', 'status', 'receiver_count')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'message': forms.Select(attrs={'class': 'form-control'}),
            'receiving_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'required': True}),
        }
