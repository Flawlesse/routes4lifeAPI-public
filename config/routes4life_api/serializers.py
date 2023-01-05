import string

import sendgrid
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import BaseUserManager
from django.contrib.gis.db import models
from django.contrib.gis.db.models import Avg, OuterRef
from django.contrib.gis.db.models.functions import GeometryDistance
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.measure import D
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer, Serializer, ValidationError
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from routes4life_api.models import Place, PlaceImage, PlaceRating, User
from routes4life_api.utils import ResetCodeManager, SessionTokenManager
from routes4life_api.validators import (
    validate_category,
    validate_distance,
    validate_latitude,
    validate_longitude,
    validate_password,
    validate_place_ordering,
    validate_rating,
)


class RegisterUserSerializer(ModelSerializer):
    confirmation_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )

    class Meta:
        model = User
        fields = ("email", "phone_number", "password", "confirmation_password")
        extra_kwargs = {
            "password": {"write_only": True, "validators": [validate_password]},
            "phone_number": {"required": False, "default": "+000000000"},
        }

    def create(self, validated_data):
        validated_data.pop("confirmation_password")
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        return User.objects.create_user(email, password, **validated_data)

    def validate(self, raw_data):
        if raw_data["password"] != raw_data["confirmation_password"]:
            raise serializers.ValidationError("Passwords don't match!")
        return raw_data


class UpdateEmailSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        kwargs["partial"] = True
        super(UpdateEmailSerializer, self).__init__(*args, **kwargs)


class ChangePasswordSerializer(ModelSerializer):
    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )
    confirmation_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )

    class Meta:
        model = User
        fields = ("password", "new_password", "confirmation_password")
        extra_kwargs = {"password": {"write_only": True}}

    def __init__(self, *args, **kwargs):
        kwargs["partial"] = True
        super(ChangePasswordSerializer, self).__init__(*args, **kwargs)

    def validate(self, raw_data):
        if any(list(map(lambda x: x not in raw_data, self.Meta.fields))):
            raise ValidationError("No fields were provided.")
        if not check_password(raw_data["password"], self.instance.password):
            raise serializers.ValidationError("Old password is incorrect!")
        if check_password(raw_data["new_password"], self.instance.password):
            raise serializers.ValidationError(
                "Changing to the same password is not allowed!"
            )
        if raw_data["new_password"] != raw_data["confirmation_password"]:
            raise serializers.ValidationError("New passwords don't match!")
        return raw_data

    def save(self):
        self.instance.set_password(self.validated_data["new_password"])
        self.instance.save()
        return self.instance


class ChangePasswordForgotSerializer(Serializer):
    email = serializers.EmailField(required=True)
    session_token = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    confirmation_password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    def validate(self, raw_data):
        norm_email = BaseUserManager.normalize_email(raw_data["email"])
        if not User.objects.filter(email=norm_email).exists():
            raise ValidationError({"email": f"No user {norm_email} was found."})
        self.instance = User.objects.get(email=norm_email)

        if len(raw_data["session_token"]) != 32 or not all(
            [
                (ch in (string.digits + string.ascii_letters))
                for ch in raw_data["session_token"]
            ]
        ):
            raise ValidationError({"session_token": "Invalid session token provided."})
        if raw_data["new_password"] != raw_data["confirmation_password"]:
            raise ValidationError("New passwords don't match!")
        if not SessionTokenManager.try_use_token(norm_email, raw_data["session_token"]):
            raise ValidationError(
                {"session_token": "Session token has expired or it is incorrect."}
            )
        return raw_data

    def save(self):
        # instance will be provided during validation!!!
        self.instance.set_password(self.validated_data["new_password"])
        self.instance.save()
        return self.instance


class FindEmailSerializer(Serializer):
    email = serializers.EmailField(required=True)

    def validate(self, raw_data):
        norm_email = BaseUserManager().normalize_email(raw_data["email"])
        if not User.objects.filter(email=norm_email).exists():
            raise ValidationError({"email": f"No user {norm_email} was found."})
        return raw_data

    def save(self):
        email = self.validated_data["email"]
        code_to_send = ResetCodeManager.get_or_create_code(email)
        sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        data = {
            "personalizations": [
                {
                    "to": [{"email": email}],
                    "subject": "Reset password code",
                }
            ],
            "from": {"email": settings.SENDGRID_SENDER_EMAIL},
            "content": [
                {
                    "type": "text/plain",
                    "value": f"Hi there, {email}. "
                    + f"Please enter this code to reset your password: {code_to_send}. "
                    + "Its is only working for 2 minutes, so you should hurry!",
                }
            ],
        }
        response = sg.client.mail.send.post(request_body=data)
        if settings.DEBUG:
            print("Trying to send an email......")
            print(response.status_code)
            print(response.body)
            print(response.headers)
        return User.objects.get(email=email)


class CodeWithEmailSerializer(Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True)

    def validate(self, raw_data):
        norm_email = BaseUserManager.normalize_email(raw_data["email"])
        if not User.objects.filter(email=norm_email).exists():
            raise ValidationError({"email": f"No user {norm_email} was found."})
        if len(raw_data["code"]) != 4 or not all(
            [(ch in string.digits) for ch in raw_data["code"]]
        ):
            raise ValidationError({"code": "Invalid code provided."})
        if not ResetCodeManager.try_use_code(norm_email, raw_data["code"]):
            raise ValidationError({"code": "Code has expired or it is incorrect."})
        return raw_data

    def save(self, **kwargs):
        """Overriden to return password reset session token."""
        email = self.validated_data["email"]
        session_token = SessionTokenManager.get_or_create_token(email)
        return session_token


class UserInfoSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "avatar",
            "is_premium",
        )
        read_only_fields = ("email", "is_premium")
        extra_kwargs = {"phone_number": {"required": False}}

    def save(self, **kwargs):
        try:
            if self.validated_data["avatar"] is None:
                self.instance.avatar.delete(save=False)
        except KeyError:
            pass
        super().save(**kwargs)


class LocationSerializer(Serializer):
    latitude = serializers.FloatField(required=True, validators=[validate_latitude])
    longitude = serializers.FloatField(required=True, validators=[validate_longitude])
    distance = serializers.FloatField(required=False, validators=[validate_distance])


class ClientValidatePlaceSerializer(ModelSerializer):
    latitude = serializers.FloatField(validators=[validate_latitude])
    longitude = serializers.FloatField(validators=[validate_longitude])
    rating = serializers.DecimalField(3, 2, required=True, validators=[validate_rating])
    secondary_images = serializers.ListField(
        child=serializers.ImageField(), required=False
    )

    class Meta:
        model = Place
        exclude = ("location", "added_by")
        extra_kwargs = {
            "main_image": {"required": True, "allow_null": False},
            "category": {"validators": [validate_category]},
        }


class CreateUpdatePlaceSerializer(GeoFeatureModelSerializer):
    rating = serializers.DecimalField(3, 2, required=True)

    class Meta:
        model = Place
        exclude = (
            "id",
            "added_by",
        )
        geo_field = "location"

    def create(self, validated_data):
        validated_data["added_by"] = self.context["user"]
        tmp_main_image = validated_data.pop("main_image")
        rating = validated_data.pop("rating")
        instance = self.Meta.model.objects.create(**validated_data)
        instance.main_image.save(tmp_main_image.name, tmp_main_image.file, True)
        instance.ratings.create(
            user=self.context["user"], place=instance, rating=rating
        )
        instance.refresh_from_db()
        return instance

    def update(self, instance, validated_data):
        tmp_main_image = validated_data.pop("main_image", None)
        rating = validated_data.pop("rating", None)
        instance = super().update(instance, validated_data)
        if tmp_main_image is not None:
            instance.main_image.save(tmp_main_image.name, tmp_main_image.file, True)
        if rating is not None:
            instance.ratings.filter(user=self.context["user"], place=instance).update(
                rating=rating
            )
        instance.refresh_from_db()
        return instance


class GetPlaceSerializer(ModelSerializer):
    added_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    rating = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    secondary_images = serializers.SerializerMethodField()
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Place
        exclude = ["location"]

    def get_rating(self, current_place):
        # NOTE: returns only rating by user who added this place
        queryset = current_place.ratings.filter(user=self.context["user"])
        if queryset.exists():
            return queryset[0].rating
        return 0

    def get_can_edit(self, current_place):
        return current_place.added_by == self.context["user"]

    def get_secondary_images(self, current_place):
        return [
            {"id": img.id, "url": img.image.url}
            for img in current_place.secondary_images.all()
        ]

    def get_latitude(self, current_place):
        return current_place.location.coords[1]

    def get_longitude(self, current_place):
        return current_place.location.coords[0]


class UpdatePlaceImagesSerializer(Serializer):
    images_to_upload = serializers.ListField(
        child=serializers.ImageField(), required=False
    )
    image_ids_to_delete = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )

    def validate(self, raw_data):
        place = self.context["place"]
        if raw_data.get("images_to_upload", None) is None:
            raw_data["images_to_upload"] = []
        if raw_data.get("image_ids_to_delete", None) is None:
            raw_data["image_ids_to_delete"] = []
        # remove duplicates
        raw_data["image_ids_to_delete"] = list(set(raw_data["image_ids_to_delete"]))

        num_delete = place.secondary_images.all().count() - len(
            raw_data["image_ids_to_delete"]
        )
        if num_delete < 0:
            raise ValidationError(
                {"image_ids_to_delete": "You want to remove more images than there is!"}
            )
        for _id in raw_data["image_ids_to_delete"]:
            if _id not in place.secondary_images.values_list("id", flat=True):
                raise ValidationError({"image_ids_to_delete": "Some ids do not exist."})

        num_upload = (
            place.secondary_images.all().count()
            - num_delete
            + len(raw_data["images_to_upload"])
        )
        if num_upload > 10:
            raise ValidationError(
                {
                    "images_to_upload": "Total of secondary images has to be less or equal to 10!"
                }
            )
        return raw_data

    def save(self):
        place = self.context["place"]
        place_images = place.secondary_images.all()
        for _id in self.validated_data["image_ids_to_delete"]:
            place_images.get(pk=_id).delete()
        place.refresh_from_db()

        for image in self.validated_data["images_to_upload"]:
            instance = PlaceImage.objects.create(place=place)
            instance.image.save(image.name, image.file, True)
        place.refresh_from_db()
        return place


class PlaceFilterSerializer(Serializer):
    latitude = serializers.FloatField(required=True, validators=[validate_latitude])
    longitude = serializers.FloatField(required=True, validators=[validate_longitude])
    distance = serializers.FloatField(required=True, validators=[validate_distance])
    categories = serializers.ListField(
        required=False, child=serializers.CharField(max_length=50)
    )
    # NOTE complex logic, update in future
    rating = serializers.DecimalField(3, 2, required=False)
    ordering = serializers.CharField(
        required=False, max_length=50, validators=[validate_place_ordering]
    )

    def get_filters_applied_queryset(self):
        data = self.validated_data
        current_point = GEOSGeometry(
            "POINT({} {})".format(data["longitude"], data["latitude"]), srid=4326
        )
        qs = self.context["user"].places.filter(location__dwithin=(current_point, 0.05))
        filter_data = {}
        filter_data["location__distance_lte"] = (
            current_point,
            D(km=data["distance"]),
        )
        if data.get("categories", None) is not None:
            filter_data["category__in"] = data["categories"]
        qs = qs.filter(**filter_data)

        if data.get("rating", None) is not None:
            place_ids_to_exclude = []
            for place in qs:
                ratings_from_author = place.ratings.filter(user=place.added_by)
                if (
                    ratings_from_author.exists()
                    and ratings_from_author[0].rating < data["rating"]
                ):
                    place_ids_to_exclude.append(place.id)
            qs = qs.exclude(id__in=place_ids_to_exclude)
        ordering = data.get("ordering", "")
        if "distance" in ordering:
            qs = qs.annotate(
                distance=GeometryDistance("location", current_point)
            ).order_by(ordering)
        elif "rating" in ordering:
            rating_subquery = PlaceRating.objects.filter(
                user=self.context["user"], place=OuterRef("pk")
            ).values("rating")
            qs = qs.annotate(
                rating=Avg(rating_subquery, output_field=models.FloatField())
            ).order_by(ordering)
        return qs


class PlaceFilterNewSerializer(Serializer):
    apply_filters = serializers.BooleanField(required=True)
    split_categories = serializers.BooleanField(required=True)
    latitude = serializers.FloatField(required=True, validators=[validate_latitude])
    longitude = serializers.FloatField(required=True, validators=[validate_longitude])
    distance = serializers.FloatField(required=False, validators=[validate_distance])
    categories = serializers.ListField(
        required=False, child=serializers.CharField(max_length=50)
    )
    # NOTE complex logic, update in future
    rating = serializers.DecimalField(3, 2, required=False)
    ordering = serializers.CharField(
        required=False, max_length=50, validators=[validate_place_ordering]
    )

    def get_filters_applied_queryset(self):
        data = self.validated_data
        current_point = GEOSGeometry(
            "POINT({} {})".format(data["longitude"], data["latitude"]), srid=4326
        )
        if data["apply_filters"]:
            qs = self.context["user"].places.filter(
                location__dwithin=(current_point, 0.05)
            )
        else:
            qs = self.context["user"].places.all()
        if not data["apply_filters"]:
            return qs

        filter_data = {}
        dist = (
            data.get("distance", None)
            if data.get("distance", None) is not None
            else 5.0
        )
        filter_data["location__distance_lte"] = (
            current_point,
            D(km=dist),
        )
        if data.get("categories", None) is not None:
            filter_data["category__in"] = data["categories"]
        qs = qs.filter(**filter_data)

        if data.get("rating", None) is not None:
            place_ids_to_exclude = []
            for place in qs:
                ratings_from_author = place.ratings.filter(user=place.added_by)
                if (
                    ratings_from_author.exists()
                    and ratings_from_author[0].rating < data["rating"]
                ):
                    place_ids_to_exclude.append(place.id)
            qs = qs.exclude(id__in=place_ids_to_exclude)
        ordering = data.get("ordering", "")
        if "distance" in ordering:
            qs = qs.annotate(
                distance=GeometryDistance("location", current_point)
            ).order_by(ordering)
        elif "rating" in ordering:
            rating_subquery = PlaceRating.objects.filter(
                user=self.context["user"], place=OuterRef("pk")
            ).values("rating")
            qs = qs.annotate(
                rating=Avg(rating_subquery, output_field=models.FloatField())
            ).order_by(ordering)
        return qs
