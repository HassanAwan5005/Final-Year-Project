"""Email codes: verification, resend, password reset and the wrong-code limit."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import OTPCode, OTPPurpose
from apps.core.exceptions import BusinessRuleViolation
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/"
NEW_PASSWORD = "BrandNew123!"


@pytest.fixture(autouse=True)
def send_inline(monkeypatch):
    """Send on this thread, so the email is in the outbox when asserted on."""

    class InlineThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(services.threading, "Thread", InlineThread)


@pytest.fixture
def unverified(buyer):
    buyer.is_email_verified = False
    buyer.save(update_fields=["is_email_verified"])
    return buyer


def emailed_code() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def reset_body(user, code):
    return {
        "email": user.email, "code": code,
        "new_password": NEW_PASSWORD, "new_password_confirm": NEW_PASSWORD,
    }


def test_signing_up_emails_a_code_that_verifies(
    api_client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            f"{URL}register/",
            {
                "email": "new@test.pk", "full_name": "New User",
                "password": PASSWORD, "password_confirm": PASSWORD,
                "phone": "03001234567", "city": "Lahore", "role": "BUYER",
            },
            format="json",
        )
    assert response.status_code == 201
    assert mail.outbox[-1].to == ["new@test.pk"]

    token = response.json()["data"]["tokens"]["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    verified = api_client.post(
        f"{URL}verify-email/", {"code": emailed_code()}, format="json"
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["is_email_verified"] is True


@pytest.mark.parametrize("which", ["first", "second"])
def test_either_code_verifies_after_asking_twice(
    buyer_client, unverified, django_capture_on_commit_callbacks, which
):
    """The Profile flow: the first email may be the one that is typed in."""
    codes = []
    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            response = buyer_client.post(f"{URL}resend-otp/", {}, format="json")
        assert response.status_code == 200
        assert mail.outbox[-1].to == [unverified.email]
        codes.append(emailed_code())

    response = buyer_client.post(
        f"{URL}verify-email/", {"code": codes[which == "second"]}, format="json"
    )
    assert response.status_code == 200
    unverified.refresh_from_db()
    assert unverified.is_email_verified is True
    # Verifying uses up every outstanding code.
    assert not OTPCode.objects.filter(user=unverified, used_at__isnull=True).exists()


def test_only_the_last_few_verification_codes_stay_live(unverified):
    codes = [
        services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
        for _ in range(services.MAX_LIVE_VERIFICATION_CODES + 1)
    ]
    assert OTPCode.objects.filter(user=unverified).count() == len(codes) - 1
    if codes[0] not in codes[1:]:
        with pytest.raises(BusinessRuleViolation, match="Incorrect code"):
            services.verify_email(unverified, codes[0])


def test_locking_also_locks_the_earlier_codes(unverified):
    first = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
    second = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
    bad = next(c for c in ("000000", "111111", "222222") if c not in (first, second))
    for _ in range(services.MAX_OTP_ATTEMPTS):
        with pytest.raises(BusinessRuleViolation):
            services.verify_email(unverified, bad)

    for code in (first, second):
        with pytest.raises(BusinessRuleViolation, match="Too many"):
            services.verify_email(unverified, code)

    # A new code replaces the locked ones instead of reopening them.
    fresh = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
    assert OTPCode.objects.filter(user=unverified).count() == 1
    services.verify_email(unverified, fresh)


def test_a_new_reset_code_replaces_the_old_one(buyer):
    services.issue_otp(buyer, OTPPurpose.PASSWORD_RESET)
    services.issue_otp(buyer, OTPPurpose.PASSWORD_RESET)

    assert OTPCode.objects.filter(user=buyer).count() == 1


def test_a_code_works_once(unverified):
    code = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
    services.verify_email(unverified, code)

    with pytest.raises(BusinessRuleViolation, match="No active"):
        services.verify_email(unverified, code)


def test_an_expired_code_is_refused(unverified):
    code = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)
    OTPCode.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

    with pytest.raises(BusinessRuleViolation, match="No active"):
        services.verify_email(unverified, code)


def test_password_reset_by_code(api_client, buyer, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(f"{URL}password-reset/", {"email": buyer.email}, format="json")

    response = api_client.post(
        f"{URL}password-reset/confirm/", reset_body(buyer, emailed_code()), format="json"
    )
    assert response.status_code == 200

    def login(password):
        return api_client.post(
            f"{URL}login/", {"email": buyer.email, "password": password}, format="json"
        ).status_code

    assert login(PASSWORD) == 401  # the old password stops working
    assert login(NEW_PASSWORD) == 200


def test_a_reset_changes_only_that_account(api_client, buyer, other_buyer):
    code = services.issue_otp(buyer, OTPPurpose.PASSWORD_RESET)
    api_client.post(
        f"{URL}password-reset/confirm/", reset_body(buyer, code), format="json"
    )

    other_buyer.refresh_from_db()
    assert other_buyer.check_password(PASSWORD)
    assert not other_buyer.check_password(NEW_PASSWORD)


def test_wrong_verification_codes_are_counted(unverified):
    code = services.issue_otp(unverified, OTPPurpose.EMAIL_VERIFICATION)

    for left in (9, 8):
        with pytest.raises(BusinessRuleViolation, match=f"{left} attempts remaining"):
            services.verify_email(unverified, wrong(code))
    assert OTPCode.objects.get(user=unverified).attempts == 2

    services.verify_email(unverified, code)
    assert unverified.is_email_verified is True


def test_a_reset_code_locks_after_too_many_wrong_guesses(api_client, buyer):
    """Even the right code is refused once the limit is reached."""
    code = services.issue_otp(buyer, OTPPurpose.PASSWORD_RESET)
    confirm = f"{URL}password-reset/confirm/"

    for _ in range(services.MAX_OTP_ATTEMPTS):
        response = api_client.post(confirm, reset_body(buyer, wrong(code)), format="json")
    assert "Too many incorrect attempts" in response.json()["message"]

    locked = api_client.post(confirm, reset_body(buyer, code), format="json")
    assert locked.status_code == 400
    buyer.refresh_from_db()
    assert buyer.check_password(PASSWORD)

    fresh = services.issue_otp(buyer, OTPPurpose.PASSWORD_RESET)
    assert api_client.post(
        confirm, reset_body(buyer, fresh), format="json"
    ).status_code == 200
