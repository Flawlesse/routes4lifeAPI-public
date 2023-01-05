import pytest
from pytest_factoryboy import register

from tests.factories import UserFactory


# register(UserFactory)
@pytest.fixture
def user_factory():
    return UserFactory
