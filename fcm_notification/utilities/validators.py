from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.conf import settings

MOBILE_REGEX = r'^01[013456789][\d]{8}$'
MOBILE_VALIDATOR = RegexValidator(MOBILE_REGEX, "Invalid mobile number.")


def validate_file_size(value):
    filesize_in_mb = value.size/(1000*1000) # converting from bytes to mb
    max_upload_size = int(settings.MAX_IMG_UPLOAD_SIZE_MB)
    
    if filesize_in_mb > max_upload_size:
        raise ValidationError("The maximum file size that can be uploaded is %s MB" % (max_upload_size))
    else:
        return value
