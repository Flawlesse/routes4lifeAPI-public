from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsSameUserOrReadonly(BasePermission):
    """Used for Place model."""

    def has_object_permission(self, request, view, place):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user == place.added_by
        )
