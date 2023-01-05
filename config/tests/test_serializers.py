import pytest
from django.contrib.auth.hashers import check_password
from faker import Faker
from routes4life_api.models import User
from routes4life_api.serializers import (
    ChangePasswordForgotSerializer,
    ChangePasswordSerializer,
    CodeWithEmailSerializer,
    FindEmailSerializer,
    RegisterUserSerializer,
    UpdateEmailSerializer,
    UserInfoSerializer,
)
from routes4life_api.utils import ResetCodeManager, SessionTokenManager

from tests.factories import fake_password


@pytest.mark.django_db
def test_register_user_serializer(user_factory):
    user_data = user_factory.build()
    password = fake_password()
    serializer = RegisterUserSerializer(
        data={
            "email": user_data.email,
            "phone_number": user_data.phone_number,
            "password": password,
            "confirmation_password": password,
        }
    )
    assert serializer.is_valid()
    new_user = serializer.save()
    assert User.objects.filter(email=new_user.email).exists()

    # DON'T PASS EMPTY PHONE NUMBER
    user_data.email = ".".join(user_data.email.split(".")[:-1]) + ".exe"
    assert new_user.email != user_data.email
    serializer = RegisterUserSerializer(
        data={
            "email": user_data.email,
            "phone_number": "  ",
            "password": password,
            "confirmation_password": password,
        }
    )
    assert serializer.is_valid() is False

    # Right way is to completely ignore it
    serializer = RegisterUserSerializer(
        data={
            "email": user_data.email,
            "password": password,
            "confirmation_password": password,
        }
    )
    assert serializer.is_valid()
    new_user = serializer.save()
    assert User.objects.filter(email=new_user.email).exists()
    assert new_user.phone_number == "+000000000"


@pytest.mark.django_db
def test_update_email_serializer(user_factory):
    test_user = user_factory.create()
    password = fake_password()
    old_email = test_user.email

    test_user.set_password(password)
    assert test_user.check_password(password)

    fake = Faker()
    serializer = UpdateEmailSerializer(instance=test_user, data={"email": fake.email()})
    assert serializer.is_valid()
    new_email = serializer.save().email
    assert old_email != new_email


@pytest.mark.django_db
def test_user_info_serializer(user_factory):
    test_user = user_factory.create()
    password = fake_password()

    old_email = test_user.email
    old_fname = test_user.first_name
    old_lname = test_user.last_name
    old_phone = test_user.phone_number

    test_user.set_password(password)
    assert test_user.check_password(password)

    fake = Faker()
    serializer = UserInfoSerializer(
        instance=test_user,
        data={
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
            "phone_number": fake.msisdn(),
        },
    )
    assert serializer.is_valid()
    serializer.save()
    assert (
        test_user.email == old_email
        and test_user.first_name != old_fname
        and test_user.last_name != old_lname
        and test_user.phone_number != old_phone
    )

    old_phone = test_user.phone_number
    serializer = UserInfoSerializer(
        instance=test_user,
        data={
            "first_name": fake.first_name(),
            "last_name": fake.last_name(),
        },
    )
    assert serializer.is_valid()
    serializer.save()
    assert (
        test_user.email == old_email
        and test_user.first_name != old_fname
        and test_user.last_name != old_lname
        and test_user.phone_number == old_phone
    )

    old_phone = test_user.phone_number
    serializer = UserInfoSerializer(
        instance=test_user, data={"phone_number": fake.msisdn()}, partial=True
    )
    assert serializer.is_valid()
    serializer.save()
    assert test_user.email == old_email and test_user.phone_number != old_phone


@pytest.mark.django_db
def test_change_password_serializer(user_factory):
    test_user = user_factory.create()
    password = fake_password()
    test_user.set_password(password)
    assert test_user.check_password(password)

    # Check for normal behavior
    new_password = fake_password()
    serializer = ChangePasswordSerializer(
        instance=test_user,
        data={
            "password": password,
            "new_password": new_password,
            "confirmation_password": new_password,
        },
    )
    assert serializer.is_valid()
    assert check_password(new_password, serializer.save().password)
    password = new_password

    # Check for blank password
    new_password = ""
    serializer = ChangePasswordSerializer(
        instance=test_user,
        data={
            "password": password,
            "new_password": new_password,
            "confirmation_password": new_password,
        },
    )
    assert serializer.is_valid() is False

    # Check for setting the same password that user owns
    serializer = ChangePasswordSerializer(
        instance=test_user,
        data={
            "password": password,
            "new_password": password,
            "confirmation_password": password,
        },
    )
    assert serializer.is_valid() is False

    # Check for non-matching passwords
    new_password = fake_password()
    confirmation_password = new_password + "xx"
    serializer = ChangePasswordSerializer(
        instance=test_user,
        data={
            "password": password,
            "new_password": new_password,
            "confirmation_password": confirmation_password,
        },
    )
    assert serializer.is_valid() is False

    # Check for wrong old password
    new_password = password
    serializer = ChangePasswordSerializer(
        instance=test_user,
        data={
            "password": fake_password(),
            "new_password": new_password,
            "confirmation_password": confirmation_password,
        },
    )
    assert serializer.is_valid() is False


@pytest.mark.django_db
def test_password_reset_serializers(user_factory):
    test_user = user_factory.create()
    password = fake_password()
    test_user.set_password(password)
    assert test_user.check_password(password)

    # Cannot find email
    serializer1 = FindEmailSerializer(
        data={
            "email": "emaildoesnotexist@email.rx",
        }
    )
    assert not serializer1.is_valid()
    # Must be right
    serializer1 = FindEmailSerializer(
        data={
            "email": test_user.email,
        }
    )
    assert serializer1.is_valid()
    user_found = serializer1.save()
    assert user_found == test_user

    code_provided = ResetCodeManager.get_or_create_code(user_found.email)
    # Try providing wrong code
    wrong_code = code_provided[:3] + chr((int(code_provided[3]) + 1) % 10)
    serializer2 = CodeWithEmailSerializer(
        data={"email": user_found.email, "code": wrong_code}
    )
    assert not serializer2.is_valid()
    # Must be right
    serializer2 = CodeWithEmailSerializer(
        data={"email": user_found.email, "code": code_provided}
    )
    assert serializer2.is_valid()
    session_token = serializer2.save()
    assert session_token == SessionTokenManager.get_or_create_token(user_found.email)

    # Try providing wrong session token
    wrong_token = SessionTokenManager.get_or_create_token("emaildoesnotexist@email.rx")
    new_password = fake_password()
    serializer3 = ChangePasswordForgotSerializer(
        data={
            "email": user_found.email,
            "session_token": wrong_token,
            "new_password": new_password,
            "confirmation_password": new_password,
        }
    )
    assert not serializer3.is_valid()

    # Try providing different passwords
    serializer3 = ChangePasswordForgotSerializer(
        data={
            "email": user_found.email,
            "session_token": session_token,
            "new_password": new_password,
            "confirmation_password": new_password + "321",
        }
    )
    assert not serializer3.is_valid()

    # Must be right
    serializer3 = ChangePasswordForgotSerializer(
        data={
            "email": user_found.email,
            "session_token": session_token,
            "new_password": new_password,
            "confirmation_password": new_password,
        }
    )
    assert serializer3.is_valid()
    user_found = serializer3.save()
    test_user.refresh_from_db()
    assert user_found == test_user
    assert check_password(new_password, test_user.password)
