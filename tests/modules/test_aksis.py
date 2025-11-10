# tests/modules/test_aksis.py

import pytest
import pytest_asyncio
from datetime import datetime
from app.backend.modules.aksis import AksisClient, AksisAuthError
from app.backend.config.config import settings # Import the settings object

# --- Pytest Markers ---
# We mark these tests as 'integration' so they can be run separately.
# The test will be skipped if the credentials are not set in the .env file.
integration_test = pytest.mark.skipif(
    not settings.AKSIS_STUDENT_USERNAME or not settings.AKSIS_STUDENT_PASSWORD,
    reason="Aksis integration tests require real credentials to be set in the .env file."
)

@pytest.fixture(scope="function")
def anyio_backend():
    # This is required for pytest-asyncio with httpx
    return "asyncio"

@pytest_asyncio.fixture(scope="function")
async def student_client():
    """
    Creates and logs in an AksisClient instance for a student.
    This fixture is run once for all tests in this module.
    """
    client = AksisClient(school_number=settings.AKSIS_STUDENT_USERNAME, password=settings.AKSIS_STUDENT_PASSWORD)
    # The login method itself is tested separately. Here we assume it works
    # to set up the client for other tests.
    await client.login()
    yield client
    # Note: No longer need to close session - using singleton HTTP client


@integration_test
class TestAksisClientIntegration:
    """A class to group all integration tests for the AksisClient."""

    @pytest.mark.asyncio
    async def test_login_success(self):
        """
        Test Case: Verifies a successful login with correct credentials.
        """
        client = AksisClient(school_number=settings.AKSIS_STUDENT_USERNAME, password=settings.AKSIS_STUDENT_PASSWORD)
        login_result = await client.login()
        
        # For a student, we expect a simple dictionary.
        assert login_result is not None
        assert login_result.get("role") == "Student"
        # Note: No longer need to close session - using singleton HTTP client

    @pytest.mark.asyncio
    async def test_login_failure(self):
        """
        Test Case: Verifies that an AksisAuthError is raised for incorrect credentials.
        """
        # Use deliberately wrong credentials
        client = AksisClient(school_number="wronguser", password="wrongpassword")
        
        # Use pytest.raises to assert that the expected exception is thrown
        with pytest.raises(AksisAuthError, match="Kullanıcı adı veya şifre hatalı."):
            await client.login()
        # Note: No longer need to close session - using singleton HTTP client

    @pytest.mark.asyncio
    async def test_get_obs_profile(self, student_client: AksisClient):
        """
        Test Case: Verifies that we can fetch the OBS profile data for a logged-in student.
        """
        profile_data = await student_client.get_obs_profile()
        
        assert profile_data is not None
        assert "full_name" in profile_data
        assert "school_number" in profile_data
        assert "image_url" in profile_data

    @pytest.mark.asyncio
    async def test_get_daily_schedule(self, student_client: AksisClient):
        """
        Test Case: Verifies that we can fetch the daily schedule.
        The result can be an empty list, which is a valid state.
        """
        # We test for today's date
        today = datetime.now()
        schedule = await student_client.get_daily_schedule(today)
        
        # The most important thing is that the function returns a list without errors.
        assert isinstance(schedule, list)

    @pytest.mark.asyncio
    async def test_get_profile_image_base64(self, student_client: AksisClient):
        """
        Test Case: Verifies that we can fetch the profile image and encode it to base64.
        """
        # First, get the profile to find the image URL
        profile_data = await student_client.get_obs_profile()
        image_url = profile_data.get("image_url")
        
        assert image_url is not None, "Could not get image URL from profile."

        # Then, get the base64 encoded image
        base64_image = await student_client.get_profile_image_base64(image_url)
        
        assert isinstance(base64_image, str)
        assert len(base64_image) > 100 # A real base64 image will be long
        
