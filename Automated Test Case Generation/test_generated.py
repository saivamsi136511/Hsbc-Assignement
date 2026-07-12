"""
ASSUMPTIONS:
- The function under test is `login` which takes two parameters: `email`
  (str) and `password` (str).
- The function returns a tuple containing the authentication token, JWT
  access token, refresh token, and an error message if any.
"""
from solution import patch

import pytest
from unittest.mock import patch
from solution import login

def test_login_happy_path():
    # --- Happy path ---
    email = "user@example.com"
    password = "Password123!"
    auth_token, jwt_access_token, refresh_token, _ = login(email, password)
    assert isinstance(auth_token, str)
    assert isinstance(jwt_access_token, str)
    assert isinstance(refresh_token, str)

@pytest.mark.parametrize("email", [
    "user@example.com",
    "user+extra@example.com",
    "user-extra@subdomain.example.com"
])
def test_login_valid_email(email):
    # --- Happy path ---
    password = "Password123!"
    auth_token, jwt_access_token, refresh_token, _ = login(email, password)
    assert isinstance(auth_token, str)
    assert isinstance(jwt_access_token, str)
    assert isinstance(refresh_token, str)

@pytest.mark.parametrize("email", [
    "",  # empty string
    " ",  # whitespace-only string
    None,  # null email
    "user@example"  # invalid domain
])
def test_login_invalid_email(email):
    # --- Error handling ---
    password = "Password123!"
    with pytest.raises(ValidationError) as exc_info:
        login(email, password)
    assert str(exc_info.value) == "Invalid email format"

@pytest.mark.parametrize("password", [
    "password",  # too short
    "a" * 7,  # exactly 7 characters (minimum boundary - 1)
    "a" * 65,  # exactly 65 characters (maximum boundary + 1)
    "!@#$%^&*()",  # no lowercase letter
    "password123!",  # no special character
    "Password123",  # no digit
])
def test_login_invalid_password(password):
    # --- Error handling ---
    email = "user@example.com"
    with pytest.raises(ValidationError) as exc_info:
        login(email, password)
    assert str(exc_info.value) == "Password does not meet complexity requirements"

@pytest.mark.parametrize("num_attempts", [1, 2, 3, 4, 5])
def test_login_lock_account(num_attempts):
    # --- Error handling ---
    email = "user@example.com"
    password = "Password123!"
    with patch("solution.login_attempts", return_value=num_attempts) as mock:
        with pytest.raises(AccountLockedError):
            login(email, password)

@pytest.mark.parametrize("num_requests", [1, 2, 3, 4, 5])
def test_login_rate_limit(num_requests):
    # --- Error handling ---
    email = "user@example.com"
    password = "Password123!"
    with patch("solution.login_attempts", return_value=num_requests) as mock:
        with pytest.raises(RateLimitError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Too many requests"

@pytest.mark.parametrize("num_requests", [11])
def test_login_rate_limit_exceeded(num_requests):
    # --- Error handling ---
    email = "user@example.com"
    password = "Password123!"
    with patch("solution.login_attempts", return_value=num_requests) as mock:
        with pytest.raises(RateLimitError) as exc_info:
            login(email, password)
        assert str(exc_info.value) == "Too many requests"

def test_login_jwt_token():
    # --- Happy path ---
    email = "user@example.com"
    password = "Password123!"
    auth_token, jwt_access_token, refresh_token, _ = login(email, password)
    assert jwt_access_token.startswith("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")