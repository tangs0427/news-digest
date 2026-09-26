"""HTML 을 Google Docs 문서로 만들어 드라이브에 올린다.

Docs API 로 문단을 하나씩 삽입하는 대신, 드라이브 업로드의 HTML -> Docs
변환 기능을 쓴다. API 호출 한 번으로 제목/목록/하이퍼링크 서식이 그대로 들어간다.

주의: drive.file 스코프는 "이 앱이 만든 파일"만 볼 수 있다. 그래서 사용자가
직접 만든 폴더 ID 를 넣으면 404 가 난다. 기본 동작은 앱이 폴더를 직접 만들고
다음 실행부터 같은 폴더를 찾아 쓰는 것이다.
"""

from __future__ import annotations

import io
import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from ..config import DeliveryConfig
from .google_auth import build_credentials

log = logging.getLogger(__name__)

DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _build_service(config: DeliveryConfig):
    credentials = build_credentials(config)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def ensure_folder(service, name: str) -> str | None:
    """앱이 만든 폴더 중 이름이 같은 것을 찾고, 없으면 새로 만든다."""
    escaped = name.replace("'", "\\'")
    query = (
        f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    try:
        found = (
            service.files()
            .list(q=query, fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = found.get("files", [])
        if files:
            return files[0]["id"]

        created = (
            service.files()
            .create(body={"name": name, "mimeType": FOLDER_MIME}, fields="id")
            .execute()
        )
        log.info("드라이브 폴더 생성: %s", name)
        return created["id"]
    except HttpError as exc:
        log.warning("폴더 준비 실패(최상위에 생성합니다): %s", exc)
        return None


def find_doc(config: DeliveryConfig, name: str) -> str | None:
    """같은 이름의 문서가 이미 있으면 URL 을 돌려준다.

    아침에 여러 회차를 돌리면서 '오늘 건 이미 보냈나'를 판단하는 근거다.
    별도 저장소 없이 드라이브 자체를 상태로 쓴다.
    """
    try:
        service = _build_service(config)
    except Exception as exc:
        log.warning("중복 확인용 인증 실패(계속 진행): %s", exc)
        return None

    escaped = name.replace("'", "\\'")
    query = f"name = '{escaped}' and mimeType = '{DOC_MIME}' and trashed = false"
    try:
        found = (
            service.files()
            .list(q=query, fields="files(id, webViewLink)", pageSize=1)
            .execute()
        )
    except HttpError as exc:
        log.warning("중복 확인 실패(계속 진행): %s", exc)
        return None

    files = found.get("files", [])
    if not files:
        return None
    return files[0].get("webViewLink") or (
        f"https://docs.google.com/document/d/{files[0]['id']}/edit"
    )


def upload_doc(config: DeliveryConfig, name: str, html: str) -> str | None:
    """문서를 만들고 열람 URL 을 돌려준다. 실패하면 None."""
    try:
        service = _build_service(config)
    except Exception as exc:  # 자격증명 실패는 메일 발송까지 막지 않는다
        log.error("Google 인증 실패: %s", exc)
        return None

    folder_id = config.drive_folder_id or ensure_folder(service, config.drive_folder_name)

    metadata: dict[str, object] = {"name": name, "mimeType": DOC_MIME}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(html.encode("utf-8")), mimetype="text/html", resumable=False
    )

    try:
        created = (
            service.files()
            .create(body=metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
    except HttpError as exc:
        log.error("문서 생성 실패: %s", exc)
        return None

    url = created.get("webViewLink") or f"https://docs.google.com/document/d/{created['id']}/edit"
    log.info("문서 생성 완료: %s", url)
    return url
