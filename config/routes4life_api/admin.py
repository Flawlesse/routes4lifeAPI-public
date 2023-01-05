from django.contrib import admin

from routes4life_api.models import Place, PlaceImage, PlaceRating, User

admin.site.register(User)
admin.site.register(Place)
admin.site.register(PlaceImage)
admin.site.register(PlaceRating)
