from django.contrib.auth import get_user_model
from django.contrib.gis.db.models import Count
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.measure import D
from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.generics import CreateAPIView, GenericAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from routes4life_api.models import Place
from routes4life_api.permissions import IsSameUserOrReadonly
from routes4life_api.serializers import (
    ChangePasswordForgotSerializer,
    ChangePasswordSerializer,
    ClientValidatePlaceSerializer,
    CodeWithEmailSerializer,
    CreateUpdatePlaceSerializer,
    FindEmailSerializer,
    GetPlaceSerializer,
    LocationSerializer,
    PlaceFilterNewSerializer,
    PlaceFilterSerializer,
    RegisterUserSerializer,
    UpdateEmailSerializer,
    UpdatePlaceImagesSerializer,
    UserInfoSerializer,
)
from routes4life_api.utils import convert_placedata_to_geojson

User = get_user_model()


class RegisterAPIView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterUserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        user = serializer.instance
        access_token = str(AccessToken.for_user(user))
        refresh_token = str(RefreshToken.for_user(user))

        return Response(
            {**serializer.data, "access": access_token, "refresh": refresh_token},
            status=201,
            headers=headers,
        )


@api_view(["PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def change_my_email(request):
    new_email = request.data.get("email")
    serializer = UpdateEmailSerializer(request.user, {"email": new_email}, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({"email": new_email}, 200)
    return Response(
        {"detail": serializer.errors.get("email", "Bad request!")},
        400,
    )


@api_view(["PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def change_my_password(request):
    serializer = ChangePasswordSerializer(
        request.user,
        data=request.data,
        partial=True,
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response({"message": "Successfully changed password."}, 200)


class UserInfoViewSet(viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserInfoSerializer
    permission_classes = (IsAuthenticated,)

    @action(detail=False, methods=["get"])
    def get_current(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(detail=False, methods=["patch"])
    def partial_update_current(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        if serializer.is_valid(raise_exception=True):
            serializer.save()
            return Response(serializer.data, 200)

    @action(detail=False, methods=["delete"])
    def delete_current(self, request):
        request.user.delete()
        return Response({"success": "User successfully deleted."}, 204)


class ForgotPasswordViewSet(viewsets.GenericViewSet):
    queryset = User.objects.all()

    def get_serializer_class(self):
        if self.action == "change_password":
            return ChangePasswordForgotSerializer
        elif self.action == "send_reset_code":
            return CodeWithEmailSerializer
        else:
            return FindEmailSerializer

    @action(detail=False, methods=["get"])
    def send_email(self, request):
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"success": f"Successfully sent a reset code to {user.email}."}, status=200
        )

    @action(detail=False, methods=["post"])
    def send_reset_code(self, request):
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_token = serializer.save()
        return Response(
            {"session_token": f"{session_token}"},
            status=200,
        )

    @action(detail=False, methods=["patch"])
    def change_password(self, request):
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"success": f"Successfully changed password for {user.email}."}, status=200
        )


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def homepage(request):
    places = GetPlaceSerializer(
        request.user.places.all(), context={"user": request.user}, many=True
    ).data
    user_data = UserInfoSerializer(request.user).data
    return Response({**user_data, "places": places})


class PlaceViewSet(viewsets.GenericViewSet):
    queryset = Place.objects.all()

    def get_permissions(self):
        if self.action in ("get_places", "create_place"):
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsSameUserOrReadonly]
        return [permission() for permission in permission_classes]

    def get_object(self):
        obj = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, obj)
        return obj

    @action(detail=False, methods=["get"])
    def get_places(self, request):
        serializer = GetPlaceSerializer(
            self.get_queryset(), many=True, context={"user": request.user}
        )
        return Response(serializer.data, 200)

    @action(detail=False, methods=["post"])
    def create_place(self, request):
        client_data_serializer = ClientValidatePlaceSerializer(data=request.data)
        client_data_serializer.is_valid(raise_exception=True)

        transformed_data = convert_placedata_to_geojson(
            client_data_serializer.validated_data
        )
        inner_serializer = CreateUpdatePlaceSerializer(
            data=transformed_data, context={"user": request.user}
        )
        inner_serializer.is_valid(raise_exception=True)
        place = inner_serializer.save()

        if "secondary_images" in transformed_data["properties"]:
            secimg_serailizer = UpdatePlaceImagesSerializer(
                data={
                    "images_to_upload": transformed_data["properties"][
                        "secondary_images"
                    ]
                },
                context={"place": place},
            )
            secimg_serailizer.is_valid(raise_exception=True)
            place = secimg_serailizer.save()

        response_serializer = GetPlaceSerializer(place, context={"user": request.user})
        return Response(response_serializer.data, 201)

    @action(detail=True, methods=["patch"], permission_classes=[IsSameUserOrReadonly])
    def update_place(self, request, pk=None):
        place = self.get_object()
        serializer = ClientValidatePlaceSerializer(
            place, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        transformed_data = convert_placedata_to_geojson(serializer.validated_data)
        inner_serializer = CreateUpdatePlaceSerializer(
            place, data=transformed_data, context={"user": request.user}, partial=True
        )
        inner_serializer.is_valid(raise_exception=True)
        place = inner_serializer.save()

        response_serializer = GetPlaceSerializer(place, context={"user": request.user})
        return Response(response_serializer.data, 200)

    @action(detail=True, methods=["delete"], permission_classes=[IsSameUserOrReadonly])
    def delete_place(self, request, pk=None):
        place = self.get_object()
        place.delete()
        return Response({"success": "Place successfully removed."}, 204)


class UpdatePlaceSecondaryImagesAPIView(GenericAPIView):
    serializer_class = UpdatePlaceImagesSerializer
    queryset = Place.objects.all()
    permission_classes = (IsSameUserOrReadonly,)

    def get_object(self):
        obj = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, obj)
        return obj

    def put(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"place": self.get_object()}
        )
        serializer.is_valid(raise_exception=True)
        place = serializer.save()
        response_serializer = GetPlaceSerializer(place, context={"user": request.user})
        return Response(response_serializer.data, 200)


class NearestPlacesAPIView(ListAPIView):
    serializer_class = GetPlaceSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        return {
            "request": self.request,
            "format": self.format_kwarg,
            "view": self,
            "user": self.request.user,
        }

    def get_queryset(self):
        lon = self.request.query_params.get("lon")
        lat = self.request.query_params.get("lat")
        dist = self.request.query_params.get("dist", 10)
        validation_serializer = LocationSerializer(
            data={"longitude": lon, "latitude": lat, "distance": dist}
        )
        validation_serializer.is_valid(raise_exception=True)
        current_point = GEOSGeometry("POINT({} {})".format(lon, lat), srid=4326)
        return self.request.user.places.filter(
            location__dwithin=(current_point, 0.1)
        ).filter(location__distance_lte=(current_point, D(km=dist)))


class SearchPlacesAPIView(ListAPIView):
    serializer_class = GetPlaceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "category", "address"]
    ordering_fields = ["name", "address"]
    ordering = ["name"]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user"] = self.request.user
        return context

    def get_queryset(self):
        return self.request.user.places.all()


class FilterPlacesAPIView(GenericAPIView):
    """
    If filters were applied, return list.
    If filters were not applied, return split by categories lists.
    """

    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "category", "address"]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        filters_applied = bool(request.data != {})
        if filters_applied:
            # POST BODY filtering
            serializer = PlaceFilterSerializer(
                data=request.data, context={"user": request.user}
            )
            serializer.is_valid(raise_exception=True)
            qs = serializer.get_filters_applied_queryset()
            # Search
            qs = self.filter_queryset(qs)
            # Pagination
            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = GetPlaceSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = GetPlaceSerializer(
                qs, many=True, context={"user": request.user}
            )
            return Response(
                {"filters_applied": filters_applied, "places": serializer.data}
            )

        categories = request.user.places.values("category").annotate(Count("category"))
        categories = dict(
            (
                (
                    item["category"],
                    request.user.places.filter(category=item["category"])[:10],
                )
                for item in categories
                if item["category__count"]
            )
        )
        data_split_by_categories = {}
        for k, qs in categories.items():
            serializer = GetPlaceSerializer(
                qs, many=True, context={"user": request.user}
            )
            data_split_by_categories[k] = serializer.data
        return Response(
            {"filters_applied": filters_applied, **data_split_by_categories}
        )


class FilterPlacesNewAPIView(GenericAPIView):
    """
    If filters were applied, return list.
    If filters were not applied, return split by categories lists.
    But here we do it manually by passing additional param.
    """

    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "category", "address"]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = PlaceFilterNewSerializer(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        filters_applied = serializer.validated_data["apply_filters"]
        qs_categ_split = serializer.validated_data["split_categories"]

        qs = serializer.get_filters_applied_queryset()
        # Search
        qs = self.filter_queryset(qs)

        if not qs_categ_split:
            # Pagination
            page = self.paginate_queryset(qs)
            if page is not None:
                serializer = GetPlaceSerializer(page, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = GetPlaceSerializer(
                qs, many=True, context={"user": request.user}
            )
            return Response(
                {
                    "filters_applied": filters_applied,
                    "is_split": qs_categ_split,
                    "places": serializer.data,
                }
            )

        categories = qs.values("category").annotate(Count("category"))
        categories = dict(
            (
                (
                    item["category"],
                    qs.filter(category=item["category"])[:10],
                )
                for item in categories
                if item["category__count"]
            )
        )
        data_split_by_categories = {}
        for k, qs in categories.items():
            serializer = GetPlaceSerializer(
                qs, many=True, context={"user": request.user}
            )
            data_split_by_categories[k] = serializer.data
        return Response(
            {
                "filters_applied": filters_applied,
                "is_split": qs_categ_split,
                **data_split_by_categories,
            }
        )


class GetPlacesByOneCategoryAPIView(ListAPIView):
    serializer_class = GetPlaceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["=category"]

    def get_queryset(self):
        return self.request.user.places.all()

    def get_serializer_context(self):
        return {
            "request": self.request,
            "format": self.format_kwarg,
            "view": self,
            "user": self.request.user,
        }
