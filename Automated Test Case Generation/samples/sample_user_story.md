# User Story: Secure User Login

## Background
As a registered user of the banking portal, I need to securely log in
to my account using my email address and password, so that I can access
my account information and perform transactions.

## Acceptance Criteria

1. The system shall accept a valid email address (RFC 5322 format) and a
   password of 8–64 characters and return a successful authentication token
   when the credentials match a registered user.

2. The system shall reject login attempts where the email address is not in
   a valid RFC 5322 format and return a ``ValidationError`` with the message
   "Invalid email format".

3. The password must contain at least one uppercase letter, one lowercase
   letter, one digit, and one special character from ``!@#$%^&*()``.
   Passwords that do not meet this policy shall be rejected with
   ``ValidationError: Password does not meet complexity requirements``.

4. The system shall lock an account after 5 consecutive failed login
   attempts within a 15-minute window. A locked account shall return
   ``AccountLockedError`` on subsequent attempts until unlocked by an
   administrator or the lock window expires.

5. The system shall not reveal whether a failed login attempt was due to
   an incorrect email (no such account) or an incorrect password, returning
   the same generic error message ``"Invalid credentials"`` in both cases.

6. Login attempts shall be rate-limited to 10 per minute per IP address.
   Requests exceeding this limit shall receive HTTP 429 with a
   ``Retry-After`` header indicating when the client may retry.

7. A successful login shall generate a JWT access token (expiry: 15 minutes)
   and a refresh token (expiry: 7 days) and return both in the response body.
   The access token shall contain the user's ID and role claims.

8. The system shall accept a password of exactly 8 characters (minimum
   boundary) and exactly 64 characters (maximum boundary). Passwords of
   7 characters or 65 characters shall be rejected with ``ValidationError``.
