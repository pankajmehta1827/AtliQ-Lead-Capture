from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .config import get_settings


def current_user(
    x_user: str | None = Header(default=None),
    x_access_code: str | None = Header(default=None),
) -> str:
    """Lightweight identity for V1: the user picks who they are and (on hosted deploys) enters the shared
    access code. Replace with SSO before real client data is connected (PRD NFR: Security)."""
    s = get_settings()
    if s.app_access_code and not hmac.compare_digest(x_access_code or "", s.app_access_code):
        raise HTTPException(401, "Invalid or missing access code")
    if not x_user or x_user not in s.seller_list:
        raise HTTPException(401, "Unknown user")
    return x_user
