from solution import MagicMock, login, patch
import pytest
from unittest.mock import patch, MagicMock
from solution import *

ASSUMPTIONS = """
Assumptions:
- The `login` function takes two parameters: `email` and `password`.
- It returns a tuple containing the authentication token and a boolean indicating success.
- The `validate_email` function checks if an email address is in valid RFC 5322 format.
- The `check_password_complexity` function checks if a password meets complexity requirements.
- The `lock_account` function locks an account after 5 consecutive failed login attempts within a 15-minute window.
- The `rate_limit_login_attempts` function rate-limits login attempts to 10 per minute per IP address.
"""

class TestSecureUserLogin:
    def test_happy_path(self):
        # --- Happy path ---
        email = "user@example.com"
        password = "Password123!"
        with patch("solution.validate_email") as mock_validate_email, \
             patch("solution.check_password_complexity") as mock_check_password_complexity, \
             patch("solution.lock_account") as mock_lock_account:
            mock_validate_email.return_value = True
            mock_check_password_complexity.return_value = True
            token, success = login(email, password)
            assert success
            assert isinstance(token, str)

    @pytest.mark.parametrize("email", [
        "user@example.com",
        "user@subdomain.example.com",
        "user+tag@example.com"
    ])
    def test_valid_email(self, email):
        # --- Happy path ---
        password = "Password123!"
        with patch("solution.validate_email") as mock_validate_email:
            mock_validate_email.return_value = True
            token, success = login(email, password)
            assert success
            assert isinstance(token, str)

    @pytest.mark.parametrize("email", [
        "",
        "invalid",
        "user@.com"
    ])
    def test_invalid_email(self, email):
        # --- Error handling ---
        password = "Password123!"
        with patch("solution.validate_email") as mock_validate_email:
            mock_validate_email.return_value = False
            with pytest.raises(ValidationError) as exc_info:
                login(email, password)
            assert str(exc_info.value) == "Invalid email format"

    @pytest.mark.parametrize("password", [
        "",
        "short",
        "verylongpasswordthatexceeds64characters"
    ])
    def test_invalid_password(self, password):
        # --- Error handling ---
        email = "user@example.com"
        with patch("solution.check_password_complexity") as mock_check_password_complexity:
            mock_check_password_complexity.return_value = False
            with pytest.raises(ValidationError) as exc_info:
                login(email, password)
            assert str(exc_info.value) == "Password does not meet complexity requirements"

    def test_account_locked(self):
        # --- Error handling ---
        email = "user@example.com"
        password = "Password123!"
        mock_lock_account = MagicMock(return_value=True)
        with patch("solution.lock_account", mock_lock_account), \
             patch("solution.check_password_complexity") as mock_check_password_complexity:
            mock_check_password_complexity.return_value = True
            for _ in range(6):
                login(email, password)
            token, success = login(email, password)
            assert not success
            assert isinstance(token, str)

    def test_rate_limited(self):
        # --- Error handling ---
        email = "user@example.com"
        password = "Password123!"
        mock_rate_limit_login_attempts = MagicMock(side_effect=[True] * 9 + [False])
        with patch("solution.rate_limit_login_attempts", mock_rate_limit_login_attempts):
            for _ in range(10):
                login(email, password)
            response = login(email, password)
            assert isinstance(response, tuple)
            assert len(response) == 2
            assert response[0] is None
            assert response[1] is False

    def test_jwt_tokens(self):
        # --- Happy path ---
        email = "user@example.com"
        password = "Password123!"
        token, success = login(email, password)
        assert isinstance(token, str)
        access_token, refresh_token = token.split(".")
        assert access_token.startswith("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert refresh_token.startswith("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")

    def test_min_password_length(self):
        # --- Error handling ---
        email = "user@example.com"
        password = "short"  # exactly 5 characters
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Password does not meet complexity requirements"

    def test_max_password_length(self):
        # --- Error handling ---
        email = "user@example.com"
        password = "verylongpasswordthatexceeds64characters"  # exactly 65 characters
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Password does not meet complexity requirements"

    def test_invalid_credentials(self):
        # --- Error handling ---
        email = "invalid@example.com"
        password = "Password123!"
        token, success = login(email, password)
        assert not success
        assert isinstance(token, str)

    @pytest.mark.parametrize("email", [
        None,
        "",
        "   "
    ])
    def test_empty_email(self, email):
        # --- Edge cases ---
        password = "Password123!"
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Invalid email format"

    @pytest.mark.parametrize("password", [
        None,
        "",
        "   "
    ])
    def test_empty_password(self, password):
        # --- Edge cases ---
        email = "user@example.com"
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Password does not meet complexity requirements"

    @pytest.mark.parametrize("email", [
        "user@example.com",
        "user@subdomain.example.com",
        "user+tag@example.com"
    ])
    def test_unicode_email(self, email):
        # --- Edge cases ---
        password = "Password123!"
        token, success = login(email, password)
        assert success
        assert isinstance(token, str)

    @pytest.mark.parametrize("password", [
        "!@#$%^&*()",
        "Password123!",
        "verylongpasswordthatexceeds64characters"
    ])
    def test_unicode_password(self, password):
        # --- Edge cases ---
        email = "user@example.com"
        token, success = login(email, password)
        assert success
        assert isinstance(token, str)

    @pytest.mark.parametrize("email", [
        "user@example.com",
        "user@subdomain.example.com",
        "user+tag@example.com"
    ])
    def test_duplicate_email(self, email):
        # --- Edge cases ---
        password = "Password123!"
        token1, success1 = login(email, password)
        assert success1
        assert isinstance(token1, str)
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Invalid email format"

    @pytest.mark.parametrize("password", [
        "!@#$%^&*()",
        "Password123!",
        "verylongpasswordthatexceeds64characters"
    ])
    def test_duplicate_password(self, password):
        # --- Edge cases ---
        email = "user@example.com"
        token1, success1 = login(email, password)
        assert success1
        assert isinstance(token1, str)
        with pytest.raises(ValidationError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Password does not meet complexity requirements"

    def test_none_email(self):
        # --- Edge cases ---
        email = None
        password = "Password123!"
        token, success = login(email, password)
        assert not success
        assert isinstance(token, str)

    def test_none_password(self):
        # --- Edge cases ---
        email = "user@example.com"
        password = None
        token, success = login(email, password)
        assert not success
        assert isinstance(token, str)