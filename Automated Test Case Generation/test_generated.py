"""
ASSUMPTIONS:
- The function to reset a password is named `reset_password`.
- It takes the following parameters: 
  - `email` (str): The user's email address.
  - `otp` (str): The one-time password received via email.
  - `new_password` (str): The new password to set.
- The function returns a boolean indicating whether the password reset was successful.
"""
from solution import reset_password
import pytest

# --- Happy path ---
def test_reset_password_success():
    """Test happy path for resetting password."""
    result = reset_password("user@example.com", "12345678", "NewP@ssw0rd")
    assert result == True

# --- Boundary value analysis ---
@pytest.mark.parametrize("email, otp, new_password, expected",
                         [
                             ("user@example.com", "12345678", "NewP@ssw0rd", True),
                             (None, "12345678", "NewP@ssw0rd", False),
                             ("", "12345678", "NewP@ssw0rd", False),
                             ("user@example.com", None, "NewP@ssw0rd", False),
                             ("user@example.com", "", "NewP@ssw0rd", False),
                             ("user@example.com", "123456789", "NewP@ssw0rd", False),
                             ("user@example.com", "1234567", "NewP@ssw0rd", False),
                             ("user@example.com", "12345678", None, False),
                             ("user@example.com", "12345678", "", False),
                             ("user@example.com", "12345678", "NewP@ssw0rd!", True)
                         ])
def test_reset_password_boundary_values(email, otp, new_password, expected):
    """Test boundary values for resetting password."""
    result = reset_password(email, otp, new_password)
    assert result == expected

# --- Edge cases ---
def test_reset_password_none_email():
    """Test None email."""
    with pytest.raises(ValueError) as exc_info:
        reset_password(None, "12345678", "NewP@ssw0rd")
    assert str(exc_info.value) == "Email is mandatory."

def test_reset_password_empty_email():
    """Test empty email."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("", "12345678", "NewP@ssw0rd")
    assert str(exc_info.value) == "Email is mandatory."

def test_reset_password_none_otp():
    """Test None OTP."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", None, "NewP@ssw0rd")
    assert str(exc_info.value) == "OTP is valid for 5 minutes."

def test_reset_password_empty_otp():
    """Test empty OTP."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "", "NewP@ssw0rd")
    assert str(exc_info.value) == "OTP is valid for 5 minutes."

def test_reset_password_none_new_password():
    """Test None new password."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", None)
    assert str(exc_info.value) == "Password minimum length is 8."

def test_reset_password_empty_new_password():
    """Test empty new password."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "")
    assert str(exc_info.value) == "Password minimum length is 8."

def test_reset_password_short_new_password():
    """Test short new password."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "NewP@ss")
    assert str(exc_info.value) == "Password minimum length is 8."

def test_reset_password_no_uppercase_new_password():
    """Test new password without uppercase."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "newp@ssw0rd")
    assert str(exc_info.value) == "Password must contain uppercase, lowercase, digit, and special character."

def test_reset_password_no_lowercase_new_password():
    """Test new password without lowercase."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "NEWP@SSW0RD")
    assert str(exc_info.value) == "Password must contain uppercase, lowercase, digit, and special character."

def test_reset_password_no_digit_new_password():
    """Test new password without digit."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "NewP@ssw")
    assert str(exc_info.value) == "Password must contain uppercase, lowercase, digit, and special character."

def test_reset_password_no_special_char_new_password():
    """Test new password without special character."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "NewPssw0rd")
    assert str(exc_info.value) == "Password must contain uppercase, lowercase, digit, and special character."

def test_reset_password_same_as_previous_new_password():
    """Test new password same as previous."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "OldP@ssw0rd")
    assert str(exc_info.value) == "New password cannot match the previous password."

def test_reset_password_expired_otp():
    """Test expired OTP."""
    with pytest.raises(ValueError) as exc_info:
        reset_password("user@example.com", "12345678", "NewP@ssw0rd")
    assert str(exc_info.value) == "Expired OTP should display an error."

def test_reset_password_max_otp_attempts():
    """Test maximum OTP attempts."""
    for _ in range(3):
        with pytest.raises(ValueError) as exc_info:
            reset_password("user@example.com", "12345678", "NewP@ssw0rd")
        assert str(exc_info.value) == "Expired OTP should display an error."