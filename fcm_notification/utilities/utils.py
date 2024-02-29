from rest_framework.exceptions import ValidationError


def check_validation(serializer):
    if serializer.is_valid():
        return serializer.validated_data
    else:
        raise ValidationError(serializer.errors)


def init_kwargs(model, arg_dict):
    model_fields = [f.name for f in model._meta.get_fields()]
    return {k: v for k, v in arg_dict.items() if k in model_fields}
