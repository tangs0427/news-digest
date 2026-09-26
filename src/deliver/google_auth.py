"""리프레시 토큰으로 Google API 자격증명을 만든다.

scripts/authorize.py 가 1회성 브라우저 동의로 리프레시 토큰을 발급하고,
이후 실행은 그 토큰만 가지고 액세스 토큰을 갱신한다.
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from ..config import DeliveryConfig

# drive.file = "이 앱이 만든 파일만" 접근. 민감 스코프가 아니라 구글 심사 대상이 아니다.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_credentials(config: DeliveryConfig) -> Credentials:
    credentials = Credentials(
        token=None,
        refresh_token=config.google_refresh_token,
        token_uri=TOKEN_URI,
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return credentials
