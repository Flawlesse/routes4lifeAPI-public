from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.gis.db import models
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from routes4life_api.utils import (
    upload_avatar_to,
    upload_place_mainimg_to,
    upload_place_secimg_to,
)


# MODELS
class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model."""

    first_name = models.CharField(_("first name"), max_length=150, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)
    phone_number = models.CharField(_("phone number"), max_length=16, blank=False)
    email = models.EmailField(unique=True)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    avatar = models.ImageField(upload_to=upload_avatar_to, blank=True, null=True)
    is_premium = models.BooleanField(default=False, null=False, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)


class Place(models.Model):
    added_by = models.ForeignKey(
        to=User, on_delete=models.CASCADE, related_name="places"
    )
    name = models.CharField(max_length=200, blank=False)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=200)
    category = models.CharField(max_length=200, blank=False)
    location = models.PointField()
    main_image = models.ImageField(
        upload_to=upload_place_mainimg_to, blank=True, null=True
    )

    def __str__(self):
        return f"{self.id}: {self.name}"


class PlaceImage(models.Model):
    place = models.ForeignKey(
        to=Place, on_delete=models.CASCADE, related_name="secondary_images"
    )
    image = models.ImageField(upload_to=upload_place_secimg_to, blank=True, null=True)

    def __str__(self):
        return f"{self.id}: To place {str(self.place)}"


class PlaceRating(models.Model):
    user = models.ForeignKey(to=User, on_delete=models.CASCADE)
    place = models.ForeignKey(
        to=Place, on_delete=models.CASCADE, related_name="ratings"
    )
    rating = models.DecimalField(max_digits=3, decimal_places=2)

    def __str__(self):
        return f"{self.id}, {self.rating}: To place {str(self.place)}"


# SIGNAL RECEIVERS
@receiver(models.signals.post_delete, sender=User)
def remove_avatar_on_delete(sender, instance, using, **kwargs):
    if instance.avatar is not None:
        instance.avatar.delete(save=False)
    return True


@receiver(models.signals.post_delete, sender=Place)
def remove_place_mainimage_on_delete(sender, instance, using, **kwargs):
    if instance.main_image is not None:
        instance.main_image.delete(save=False)
    return True


@receiver(models.signals.post_delete, sender=PlaceImage)
def remove_place_image_on_delete(sender, instance, using, **kwargs):
    if instance.image is not None:
        instance.image.delete(save=False)
    return True
