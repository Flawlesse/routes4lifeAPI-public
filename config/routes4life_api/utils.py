import os
import random
import string
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from rest_framework.views import exception_handler


class ResetCodeManager:
    __ttl = timedelta(minutes=2)

    @classmethod
    def get_or_create_code(cls, email: str) -> str:
        key = email + "__code"
        code = cache.get(key, None)
        if code is not None:
            return code
        code = "".join(random.choices(string.digits, k=4))
        cache.add(key, code, timeout=cls.__ttl.seconds)
        return cache.get(key)

    @classmethod
    def try_use_code(cls, email: str, code: str) -> bool:
        key = email + "__code"
        if cache.get(key) != code:
            return False
        cache.delete(key)
        return True


class SessionTokenManager:
    __ttl = timedelta(minutes=10)

    @classmethod
    def get_or_create_token(cls, email: str) -> str:
        key = email + "__token"
        token = cache.get(key, None)
        if token is not None:
            return token
        token = "".join(random.choices(string.digits + string.ascii_letters, k=32))
        cache.add(key, token, timeout=cls.__ttl.seconds)
        return cache.get(key)

    @classmethod
    def try_use_token(cls, email: str, token: str) -> bool:
        key = email + "__token"
        if cache.get(key) != token:
            return False
        cache.delete(key)
        return True


def convert_placedata_to_geojson(data):
    transformed_data = {}
    if data.get("latitude") is not None and data.get("longitude") is not None:
        latitude, longitude = (
            data.pop("latitude"),
            data.pop("longitude"),
        )
        # According to WKT standard is: POINT (x y), or POINT (Lon Lat)
        transformed_data["geometry"] = {
            "type": "Point",
            "coordinates": [
                longitude,
                latitude,
            ],
        }
    properties = {**data}
    transformed_data["type"] = "Feature"
    transformed_data["properties"] = properties
    return transformed_data


def custom_exception_handler(exc, context):
    newdata = dict()
    newdata["errors"] = []

    def get_list_from_errors(data):
        to_return = []
        if not isinstance(data, (list, dict)):
            to_return.append(data)
        elif isinstance(data, list):
            for err in data:
                to_return.extend(get_list_from_errors(err))
        elif isinstance(data, dict):
            for err in data.values():
                to_return.extend(get_list_from_errors(err))
        return to_return

    response = exception_handler(exc, context)
    if response is not None:
        newdata["errors"].extend(get_list_from_errors(response.data))
        newdata["old_repr"] = response.data
        response.data = newdata
    return response


def upload_avatar_to(instance, filename):
    """Instance is of type User."""
    return (
        f"{settings.UPLOAD_ROOT}/{instance.email.replace('@', 'AT')}"
        + f"/avatar{os.path.splitext(filename)[1]}"
    )


def upload_place_mainimg_to(instance, filename):
    """Instance is of type Place."""
    return (
        f"{settings.UPLOAD_ROOT}/places/{instance.id}"
        + f"/main-image{os.path.splitext(filename)[1]}"
    )


def upload_place_secimg_to(instance, filename):
    """Instance is of type PlaceImage."""
    return (
        f"{settings.UPLOAD_ROOT}/places/{instance.place.id}"
        + f"/secondary_img_{instance.id}{os.path.splitext(filename)[1]}"
    )
