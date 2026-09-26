"""1회성 Google OAuth 동의 -> 리프레시 토큰 발급.

로컬에서 한 번만 실행합니다. 브라우저가 열리고, 동의하면 터미널에
GitHub Secrets 에 넣을 값이 출력됩니다.

    python scripts/authorize.py

발급된 리프레시 토큰은 화면에만 출력되고 파일로 저장되지 않습니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from src.config import load_delivery  # noqa: E402
from src.deliver.google_auth import SCOPES  # noqa: E402


def _prompt(label: str, existing: str) -> str:
    if existing:
        print(f"{label}: .env 값 사용 ({existing[:12]}...)")
        return existing
    value = input(f"{label} 붙여넣기: ").strip()
    if not value:
        raise SystemExit(f"{label} 가 필요합니다.")
    return value


def main() -> int:
    config = load_delivery()

    print("=" * 62)
    print("Google Cloud Console > API 및 서비스 > 사용자 인증 정보에서")
    print("'데스크톱 앱' 유형의 OAuth 클라이언트를 만든 뒤 값을 준비하세요.")
    print("=" * 62)

    client_id = _prompt("GOOGLE_CLIENT_ID", config.google_client_id)
    client_secret = _prompt("GOOGLE_CLIENT_SECRET", config.google_client_secret)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # access_type=offline + prompt=consent 여야 리프레시 토큰이 내려온다.
    credentials = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    if not credentials.refresh_token:
        print("\n리프레시 토큰이 발급되지 않았습니다.")
        print("계정의 기존 권한을 https://myaccount.google.com/permissions 에서")
        print("삭제한 뒤 다시 실행해 보세요.")
        return 1

    print("\n" + "=" * 62)
    print("발급 완료. 아래 값을 .env 와 GitHub Secrets 양쪽에 넣으세요.")
    print("=" * 62)
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}")
    print("=" * 62)
    print("주의: OAuth 동의 화면의 게시 상태가 '테스트'이면 리프레시 토큰이")
    print("7일 뒤 만료됩니다. '프로덕션'으로 게시해야 계속 유효합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
