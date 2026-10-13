"""Disabled-by-default, request-bound MSG91 OTP widget adapter.

Official contracts (checked 2026-10-08):
https://docs.msg91.com/otp-widget
https://github.com/Walkover-Web-Solution/msg91-sendOTP_JS_SDK
https://github.com/Walkover-Web-Solution/SendOTP-flutter-SDK/blob/main/example/example.dart
https://github.com/Walkover-Web-Solution/sendotp-kotlin-sdk/blob/main/app/src/main/java/com/msg91/sendotp/MainActivity.kt
https://github.com/Walkover-Web-Solution/msg91-php-plugins/blob/main/src/Services/OTPService.php

Send's success/message request ID and verify's message field are shown by the
SDK examples; the docs describe a JWT from verify. Their combined exact success
shape is NOT account-tested. MSG91_CONTRACT_VERIFIED must remain false until an
operator verifies this shape, six-digit SMS delivery, invalid/expired codes and
server token verification on their configured widget. No alternate field names,
invisible-verification flow, local JWT claims, or classic phone-only OTP fallback
are accepted. The provider's own OTP expiry is not configured by this adapter;
our signed handle and PhoneAuthService independently enforce <=300 seconds.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import re
import time
import uuid


class SMSProviderUnavailable(Exception):
    """Sanitized failure; never includes provider bodies, tokens or phone numbers."""


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _https_post(path, payload):
    # Fixed host, no redirects/proxy redirects, no credentials in URL. Bounded
    # socket wait and response size; no automatic retries that could send twice.
    connection = http.client.HTTPSConnection("control.msg91.com", timeout=10)
    try:
        connection.request("POST", "/api/v5/widget/" + path,
                           body=json.dumps(payload).encode("utf-8"),
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise SMSProviderUnavailable("SMS provider unavailable")
        body = response.read(16385)
        if len(body) > 16384:
            raise SMSProviderUnavailable("SMS provider unavailable")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise SMSProviderUnavailable("SMS provider unavailable")
        return result
    except Exception:
        raise SMSProviderUnavailable("SMS provider unavailable") from None
    finally:
        connection.close()


class MSG91Provider:
    def __init__(self, *, widget_id=None, token_auth=None, auth_key=None,
                 handle_secret=None, contract_verified=False, transport=None, clock=None):
        self.widget_id, self.token_auth, self.auth_key = widget_id, token_auth, auth_key
        secret = handle_secret.encode("utf-8") if isinstance(handle_secret, str) else handle_secret
        self.ready = (contract_verified is True and isinstance(secret, bytes) and len(secret) >= 32
                      and all(isinstance(v, str) and bool(v.strip()) and len(v) <= 1024
                              for v in (widget_id, token_auth, auth_key)))
        self._key = (hmac.new(secret, b"msg91-phone-handle-v1\0" + widget_id.encode(), hashlib.sha256).digest()
                     if self.ready else None)
        self._post = transport or _https_post
        self._clock = clock or time.time

    def _call(self, path, payload):
        try:
            result = self._post(path, payload)
        except Exception:
            raise SMSProviderUnavailable("SMS provider unavailable") from None
        if not isinstance(result, dict):
            raise SMSProviderUnavailable("SMS provider unavailable")
        return result

    def _widget(self, **fields):
        return {"widgetId": self.widget_id, "tokenAuth": self.token_auth, **fields}

    def send(self, phone, *, challenge_id, expires_in=300):
        if not self.ready:
            raise SMSProviderUnavailable("SMS provider unavailable")
        try:
            valid_id = isinstance(challenge_id, str) and str(uuid.UUID(challenge_id)) == challenge_id
        except (ValueError, AttributeError):
            valid_id = False
        if (not isinstance(phone, str) or not re.fullmatch(r"\+91[6-9][0-9]{9}", phone)
                or not valid_id or type(expires_in) is not int or not 1 <= expires_in <= 300):
            raise ValueError("Invalid phone challenge")
        issued = int(self._clock())
        result = self._call("sendOtpMobile", self._widget(identifier=phone[1:]))
        request_id = result.get("message")
        if (result.get("type") != "success" or "access-token" in result
                or (result.get("invisibleVerified") is not None and result.get("invisibleVerified") is not False)
                or not isinstance(request_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id)):
            raise SMSProviderUnavailable("SMS provider unavailable")
        # This handle is authenticated, not encrypted. It is server-only state,
        # never a client response. PhoneAuthService handles atomic one-time use.
        body = _encode(json.dumps([phone, request_id, challenge_id, issued, expires_in],
                                  separators=(",", ":")).encode())
        signature = _encode(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
        return body + "." + signature

    def _read_handle(self, handle):
        try:
            if not isinstance(handle, str) or len(handle) > 512:
                return None
            body, signature = handle.split(".")
            expected = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _decode(signature)):
                return None
            phone, request_id, challenge_id, issued, ttl = json.loads(_decode(body))
            if (not re.fullmatch(r"\+91[6-9][0-9]{9}", phone)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id)
                    or str(uuid.UUID(challenge_id)) != challenge_id
                    or type(issued) is not int or type(ttl) is not int or not 1 <= ttl <= 300
                    or not issued <= self._clock() < issued + ttl):
                return None
            return request_id
        except (ValueError, TypeError, AttributeError, UnicodeError):
            return None

    def verify(self, handle, code):
        if not self.ready or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            return False
        request_id = self._read_handle(handle)
        if request_id is None:
            return False
        result = self._call("verifyOtp", self._widget(reqId=request_id, otp=code))
        token = result.get("message")
        if (result.get("type") != "success" or not isinstance(token, str)
                or len(token) > 8192
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)):
            return False
        # Only a token received directly from the bound reqId verification can
        # reach this call. Never accept tokens supplied by the client, decode JWT
        # identity claims, or infer success from token shape alone.
        verified = self._call("verifyAccessToken", {"authkey": self.auth_key, "access-token": token})
        return verified.get("type") == "success" and self._read_handle(handle) is not None
