# news-digest

매일 아침 07:00(KST)에 뉴스를 모아 **Google Docs 문서로 만들고 메일로 보내주는** 시스템입니다.

- 실행: GitHub Actions cron (PC를 켜둘 필요 없음)
- 가공: 맨 위 **'오늘의 흐름'** 총평 + 기사별 **한 줄 요약** (Gemini 무료 티어, 하루 6회 호출)
- 카테고리: 시장·거시 / 산업·기업 / AI·테크 / 스타트업·투자 / 채용·커리어

```
수집(21개 RSS) → 노이즈 필터 → 중복 제거 → 카테고리별 12건
      → Gemini 요약(카테고리별 호출) → HTML → Google Docs 업로드 → Gmail 발송
```

**요약은 실패해도 발송을 막지 않습니다.** 키가 없거나 API가 죽으면 요약만 빠진 채
헤드라인 다이제스트가 정상적으로 나갑니다.

---

## 1. 로컬에서 먼저 돌려보기

```powershell
cd news-digest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 피드 21개가 살아 있는지 점검
python -m src.main --check-feeds

# 요약 없이 헤드라인만 수집해서 output\<날짜>.html 로 저장
python -m src.main --dry-run --no-ai
```

`output\` 폴더의 HTML을 브라우저로 열어 내용이 마음에 드는지 먼저 확인하세요.
여기까지는 인증 정보가 전혀 필요 없습니다.

---

## 1-2. AI 요약 켜기 (Gemini, 무료)

1. [Google AI Studio](https://aistudio.google.com/apikey)에서 **Create API key** — 무료, 카드 등록 불필요
2. `.env.example`을 `.env`로 복사하고 `GEMINI_API_KEY`에 붙여넣기
3. 요약까지 포함해서 돌려보기:

```powershell
python -m src.main --dry-run
```

### 무료 한도를 꼭 알아두세요

**Gemini 무료 티어는 모델당 하루 20회 요청**입니다. 이 시스템은 정상 동작 시
**하루 6회**를 씁니다 (카테고리 5개 + 오늘의 흐름 1개).

기사 60건을 한 번에 보내면 1회로 끝나지만 API 가 503 을 돌려줍니다. 12건 단위로
끊어야 통과합니다(실측). 그래서 카테고리별로 나눠 부릅니다.

한도를 지키려고 코드에 둔 장치:

| 장치 | 값 | 이유 |
|---|---|---|
| 총 호출 상한 | 16회 | 재시도가 하루치 한도를 먹어치우지 못하게 |
| 시간 예산 | 240초 | 넘으면 만든 것만 들고 발송 |
| 일일 한도 감지 | 즉시 모델 교체 | 하루 한도는 기다려도 안 풀림. 한도는 **모델별**로 따로 |
| 추론(thinking) | 끔 | 켜져 있으면 503 유발 (실측) |

로컬에서 `--dry-run` 을 여러 번 돌리면 그날 한도를 다 쓸 수 있습니다.
그러면 아침 발송에서 요약이 빠집니다 — **테스트는 `--no-ai` 로 하세요.**

한도는 **태평양 자정**에 리셋됩니다 (한국 시간 오후 4~5시경). 아침 7시 발송은
리셋 후 15시간쯤 지난 시점이라 한도가 넉넉합니다.

> **요약의 한계를 알아두세요.** 구글 뉴스로 들어온 기사는 **제목만 있고 본문이 없습니다.**
> 현재 원문 리드 문단이 확보되는 건 전체의 약 1/3이고, 채용·커리어 카테고리는 0%입니다.
> 그래서 프롬프트에 "본문이 없으면 제목 범위 안에서만 쓰고, 모르는 수치·인명·날짜를
> 지어내지 말 것"을 명시해 두었습니다. 그래도 요약은 **원문 확인 전의 참고용**으로만 쓰세요.

---

## 2. Google 인증 준비 (1회성, 약 10분)

문서를 만들려면 Google Drive API 권한이 필요합니다.
이 프로젝트는 **`drive.file` 스코프**만 씁니다 — "이 앱이 만든 파일"에만 접근하는 범위라
구글 심사(verification) 대상이 아니고, 기존 드라이브 파일은 건드릴 수 없습니다.

### 2-1. Cloud 프로젝트와 API

1. [Google Cloud Console](https://console.cloud.google.com/) → 새 프로젝트 생성 (이름 아무거나)
2. **API 및 서비스 → 라이브러리** → `Google Drive API` 검색 → **사용 설정**

### 2-2. OAuth 동의 화면

3. **API 및 서비스 → OAuth 동의 화면**
   - User Type: **외부(External)**
   - 앱 이름, 지원 이메일, 개발자 연락처만 채우면 됩니다
   - 범위(scope) 추가 화면은 건너뛰어도 됩니다
4. ⚠️ **게시 상태를 "프로덕션"으로 게시하세요.**
   "테스트" 상태로 두면 **리프레시 토큰이 7일 뒤 만료돼서 매주 다시 발급해야 합니다.**
   `drive.file`은 민감 범위가 아니라 프로덕션 게시에 별도 심사가 붙지 않습니다.

### 2-3. OAuth 클라이언트

5. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**
   - 애플리케이션 유형: **데스크톱 앱**
   - 생성된 **클라이언트 ID**와 **클라이언트 보안 비밀번호**를 복사

### 2-4. 리프레시 토큰 발급

```powershell
python scripts\authorize.py
```

클라이언트 ID/보안 비밀번호를 붙여넣으면 브라우저가 열립니다.
"이 앱은 Google에서 확인하지 않았습니다" 경고가 나오면 **고급 → 안전하지 않은 페이지로 이동**을 누르세요
(본인이 만든 앱이라 정상입니다). 동의하면 터미널에 `GOOGLE_REFRESH_TOKEN`이 출력됩니다.

---

## 3. Gmail 앱 비밀번호

메일 발송은 SMTP를 씁니다. 계정 비밀번호가 아니라 **앱 비밀번호**가 필요합니다.

1. Google 계정에 **2단계 인증**이 켜져 있어야 합니다
2. [앱 비밀번호](https://myaccount.google.com/apppasswords)에서 16자리 발급

---

## 4. 로컬 전체 실행 테스트

`.env.example`을 `.env`로 복사하고 값을 채운 뒤:

```powershell
python -m src.main
```

드라이브에 `뉴스 다이제스트` 폴더와 문서가 생기고 메일이 오면 성공입니다.
`.env`는 `.gitignore`에 들어 있어 커밋되지 않습니다.

---

## 5. GitHub Actions에 올리기

```powershell
git init
git add .
git commit -m "feat: 뉴스 다이제스트 초기 구현"
git branch -M main
git remote add origin https://github.com/<계정>/news-digest.git
git push -u origin main
```

저장소 **Settings → Secrets and variables → Actions → New repository secret**에 등록:

| Secret | 값 |
|---|---|
| `GEMINI_API_KEY` | 1-2에서 발급한 Gemini 키 |
| `GOOGLE_CLIENT_ID` | 2-3에서 받은 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 2-3에서 받은 보안 비밀번호 |
| `GOOGLE_REFRESH_TOKEN` | 2-4에서 발급한 토큰 |
| `GMAIL_ADDRESS` | 보내는 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | 3에서 발급한 16자리 |
| `MAIL_TO` | 받을 주소 (비우면 `GMAIL_ADDRESS`로) |

등록 후 **Actions 탭 → 뉴스 다이제스트 → Run workflow**로 한 번 수동 실행해서 확인하세요.

---

## 6. 내용 바꾸기

관심사가 바뀌면 [`config/sources.yaml`](config/sources.yaml) **하나만** 고치면 됩니다. 코드는 건드릴 필요 없습니다.

```yaml
lookback_hours: 30      # 몇 시간 전까지의 기사를 볼지
max_per_category: 12    # 카테고리당 실을 기사 수

categories:
  - key: market
    label: "시장 · 거시"
    feeds:
      - name: "구글뉴스 · 증시"
        type: google_news
        query: "코스피 OR 코스닥 -특징주"   # OR 와 -제외어 사용 가능
```

- **카테고리 추가/삭제**: `categories` 항목을 늘리거나 지우면 됩니다
- **노이즈 제거**: `filters.exclude_title_patterns`에 정규식 추가
- **매체명 정리**: 출처가 도메인으로 나오면 `source_aliases`에 추가
- 고친 뒤에는 `python -m src.main --check-feeds`로 피드가 살아 있는지 확인하세요

발송 시각은 [`.github/workflows/daily.yml`](.github/workflows/daily.yml)의 cron에서 바꿉니다.
**UTC 기준**이라 KST에서 9시간을 빼야 합니다 (07:00 KST → `0 22 * * *`).

---

## 7. 아침에 네 번 시도하는 이유

Gemini 무료 티어가 혼잡하면 요약이 실패합니다. 한 번만 시도하면 그날은 그냥
헤드라인만 받게 되므로, 아침에 **네 번** 시도합니다.

| 시각(KST) | 동작 |
|---|---|
| 06:00 | 시도. **요약이 온전할 때만** 문서 생성 + 메일 발송 |
| 06:20 | 오늘 문서가 이미 있으면 즉시 종료. 없으면 재시도 |
| 06:40 | 〃 |
| 07:00 | **마지막** — 요약이 없어도 무조건 발송 |

"오늘 것을 이미 보냈는지"는 드라이브에서 `뉴스 다이제스트 YYYY-MM-DD (요일)`
문서를 찾아 판단합니다. 별도 저장소가 필요 없고, 중간에 실패해도 자기복구됩니다.

> 문서 제목의 요일은 `%a` 가 아니라 고정 한글 배열로 만듭니다. `%a` 는 실행 환경
> 로케일에 따라 `Thu`/`목`/`木` 으로 갈리는데, 그러면 회차마다 제목이 달라져
> 중복 판단이 깨지고 하루에 여러 번 발송됩니다.

수동 실행(Actions 탭 → Run workflow)에는 **"오늘 문서가 이미 있어도 새로 만들기"**
체크박스가 있습니다. 평소에는 끄고 쓰세요 — 켜면 문서가 하나 더 생깁니다.

---

## 알아둘 점

- **GitHub Actions cron은 정시를 보장하지 않습니다.** 혼잡하면 10~30분 늦게 돌 수 있습니다.
- **저장소가 60일간 활동이 없으면 스케줄이 자동 비활성화됩니다.** 메일이 끊기면 Actions 탭을 먼저 확인하세요.
- **OAuth 동의 화면이 "테스트" 상태면 리프레시 토큰이 7일 만에 만료됩니다.** 2-2의 프로덕션 게시를 꼭 하세요.
- **AI 요약은 원문 확인을 대신하지 않습니다.** 기사 2/3은 제목만 보고 쓴 요약입니다. 중요한 건 링크를 눌러 확인하세요.
- Gemini 모델을 바꾸려면 `GEMINI_MODEL` 환경변수만 고치면 됩니다 (기본값 `gemini-2.5-flash`).
- `drive.file` 스코프라 **직접 만든 폴더의 ID를 `DRIVE_FOLDER_ID`에 넣으면 404가 납니다.** 기본값대로 앱이 폴더를 직접 만들게 두세요.
- 구글 뉴스 링크는 `news.google.com` 리다이렉트 주소입니다. 클릭하면 원문으로 이동합니다.

## 구조

```
config/sources.yaml       수집 대상·필터·별칭 (여기만 고치면 됨)
src/config.py             YAML + 환경변수 로딩
src/models.py             Article / Digest 데이터 구조
src/collect/rss.py        피드 수집, 제목·출처 정리
src/collect/filters.py    노이즈 기사 제외
src/collect/dedupe.py     중복 기사 병합 (한국어 어미 변화 대응)
src/pipeline.py           수집 → 필터 → 중복 제거 → 조립
src/summarize/prompt.py   요약 프롬프트·응답 스키마 (지어내기 방지 규칙)
src/summarize/gemini.py   Gemini 호출 (하루 1회, 실패해도 발송은 진행)
src/render/doc_html.py    Google Docs 변환용 HTML
src/render/email_html.py  메일 본문 HTML (인라인 스타일)
src/deliver/google_auth.py  리프레시 토큰 → 자격증명
src/deliver/google_docs.py  드라이브 업로드 (HTML → Docs 변환)
src/deliver/mail.py       Gmail SMTP 발송
scripts/authorize.py      1회성 OAuth 동의
tests/test_collect.py     회귀 테스트 (python -m unittest discover -s tests)
```
