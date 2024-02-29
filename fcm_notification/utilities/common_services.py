import os
from uuid import uuid4
from datetime import datetime


def create_file_name(filename):
    base_filename, file_extension = os.path.splitext(filename)
    return '{}{}'.format(uuid4().hex, file_extension)


def image_upload_path(instance, uploaded_filename):
    new_filename = create_file_name(uploaded_filename)
    return 'uploads/{}/{}'.format(datetime.now().strftime("%Y/%m/%d"), new_filename)


def notification_number_file_upload_path(instance, uploaded_filename):
    new_filename = create_file_name(uploaded_filename)
    return os.path.join('notification_request', datetime.now().strftime("%Y%m%d"), new_filename)
