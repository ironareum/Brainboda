# Brainboda — YouTube Automation Pipeline

> **Psychology · Human Behavior · Success Mindset**
> Channel: Brainboda | Language: English | Platform: YouTube

---

## 프로젝트 개요

Wikipedia 심리학 facts를 자동으로 수집해서 영어 YouTube 영상(메인 10 facts)을 완전 자동 생성·업로드하는 Python 파이프라인.

**비용 원칙: 완전 무료** — ElevenLabs 등 유료 TTS API 사용 금지.
AI 스크립트 생성 시 Claude Haiku 사용 (~$0.008/영상).

---

## 채널 전략 (목표 기준)

### 목표
- **수익화 달성**: 구독자 1,000명 + 시청 4,000시간 (YPP)
- **장기**: 심리학 → 뇌과학, 경제, 우주 등 카테고리 확장

### 업로드 스케줄

| 요일 | 업로드 | 비고 |
|------|--------|------|
| 월/수/금/토 | **쇼츠** | 메인 영상에서 가장 임팩트 있는 팩트 1개 발췌 |
| 화/목 | **메인 영상** | 10 facts, 8-12분 |
| 일 | 없음 | |

> ⚠️ **같은 날 메인+쇼츠 절대 금지** — 알고리즘이 채널을 Shorts 채널로 분류해 메인 추천 차단됨

- 공개 시간: **20:00 UTC (미국 동부 오후 3시)** — 직장인 퇴근 후 피크타임
- 업로드는 비공개 → +1일 후 자동 공개 예약

### 쇼츠 전략
- 쇼츠는 **반드시 메인에서 발췌** (별도 주제 X)
- 쇼츠 설명란에 메인 영상 링크 → 채널 유입 유도
- 쇼츠 목적: 수익(X) → 구독자·노출(O)
- 메인 목적: 구독자(O) + 수익(O, CPM $3-8)

### 성장 단계
- **Phase 1 (1-3개월)**: 메인 주2 + 쇼츠 주4, 채널 정체성 확립
- **Phase 2 (1K 구독 이후)**: 쇼츠 주3으로 축소, 퀄리티 집중

### 재생목록
- `How Your Mind Works` (ID: `PLAs3NOlOTcp0`)

---

## 기술 스택

| 역할 | 도구 |
|---|---|
| Facts 수집 | Wikipedia REST API (영어판) |
| TTS | edge-tts (`en-US-GuyNeural`) |
| 이미지 | Pixabay API + Pexels API |
| 영상 렌더링 | MoviePy (FFmpeg 기반) |
| 썸네일 | Pillow |
| 업로드 | YouTube Data API v3 |

---

## 폴더 구조

```
Brainboda/
├── config/
│   ├── channel.py              ← 채널 설정 (TTS 보이스, API 키, 해상도 등)
│   ├── fonts/
│   │   ├── download_fonts.py   ← Poppins TTF 다운로드 스크립트
│   │   ├── Poppins-Bold.ttf
│   │   ├── Poppins-SemiBold.ttf
│   │   └── Poppins-Regular.ttf
│   └── bgm/
│       ├── hook/               ← Hook 구간 BGM (bgm_01.mp3, bgm_02.mp3 ...)
│       └── facts/              ← Facts 구간 BGM (bgm_01.mp3, bgm_02.mp3 ...)
│
├── data/
│   ├── used_concepts.json      ← AI 모드 테마·컨셉 중복 방지 (사용중)
│   ├── used_image_urls.json    ← 이미지 URL 중복 방지 (사용중)
│   ├── used_shorts_facts.json  ← 쇼츠로 발췌된 팩트 트래킹 (사용중)
│   └── latest_main_script.json ← 최신 메인 스크립트 (Shorts Actions가 참조)
│
├── pipeline/
│   ├── 01_fetch_facts.py       ← Wikipedia EN → 심리학 facts 수집
│   ├── 02_build_script.py      ← facts 선택 → 영어 스크립트 JSON 생성
│   ├── 03_tts.py               ← edge-tts → MP3 나레이션
│   ├── 04_fetch_visuals.py     ← Pixabay/Pexels → 이미지 수집
│   ├── 05_render_video.py      ← MoviePy → MP4 렌더링
│   ├── 06_thumbnail.py         ← Pillow → 썸네일 생성 (4종 레이아웃 로테이션)
│   ├── 07_upload.py            ← YouTube Data API → 업로드
│   └── clean_facts_csv.py      ← facts_raw.csv 품질 필터 재실행 유틸리티
│
├── output/
│   └── {YYYYMMDD_HHMMSS}_main/
│       ├── script.json
│       ├── thumbnail.jpg
│       ├── video.mp4
│       ├── audio/
│       │   ├── hook.mp3
│       │   ├── fact_01.mp3 ~ fact_10.mp3
│       │   ├── outro.mp3
│       │   └── full_narration.mp3
│       └── visuals/
│           ├── _hook/          ← Hook 전용 이미지 (일반 심리학 이미지 6장)
│           └── {fact_id}/      ← 팩트별 이미지 10장
│               ├── img_01.jpg  ← 타이틀카드 전용 (나레이션에서 미사용)
│               └── img_02~10.jpg ← 나레이션 슬라이드용
│
├── logs/
├── run.py                      ← 전체 파이프라인 진입점
└── README.md
```

---

## CLI 사용법

```bash
# 전체 파이프라인 (생성 + 업로드)
python run.py --type main

# 테스트 모드 (2 facts만 렌더, 업로드 스킵)
python run.py --type main --test

# 업로드 스킵
python run.py --type main --skip-upload

# 특정 주제로 facts 수집 후 생성
python run.py --type main --topic "manipulation"

# facts_raw.csv 품질 필터 재실행
python pipeline/clean_facts_csv.py --dry-run   # 미리보기
python pipeline/clean_facts_csv.py             # 실제 적용
```

---

## 파이프라인 흐름

```
[Step 01] 01_fetch_facts.py
  Wikipedia REST API → facts_raw.csv (누적 append)
  ↓ pool < 10개면 자동 실행, 충분하면 스킵

[Step 02] 02_build_script.py
  facts_raw.csv → 10개 랜덤 선택 → script.json
  used_facts.json에 선택된 ID 마킹 (중복 방지)

[Step 03] 03_tts.py
  script.json → edge-tts → hook.mp3, fact_01~10.mp3, outro.mp3

[Step 04] 04_fetch_visuals.py
  script.json → Pixabay/Pexels → visuals/ 이미지 수집
  - Hook: visuals/_hook/ (일반 심리학 이미지, 팩트와 별개)
  - Facts: visuals/{fact_id}/ (팩트당 10장, 3가지 검색어 변형 사용)

[Step 05] 05_render_video.py
  audio/ + visuals/ → MoviePy → video.mp4

[Step 06] 06_thumbnail.py
  script.json + visuals/ → Pillow → thumbnail.jpg

[Step 07] 07_upload.py
  video.mp4 + thumbnail.jpg → YouTube Data API v3
```

---

## Facts 품질 필터

`02_build_script.py`와 `clean_facts_csv.py`에 동일한 필터 로직 적용.

### 거절 기준 (REJECT_IDS)

ID 기반으로 명시적 차단 — category 필드는 모두 "psychology"로 세팅되어 신뢰 불가.

```python
REJECT_IDS = {
    # 비심리학 분야 / 단체 / 저널
    "4or", "19_to_zero", "animal_studies", "anthropology",
    "black_american_anthropology",
    "association_for_behavior_analysis_international",
    "association_for_contextual_behavioral_science",
    "cog_s_ladder", "ghost_job", "phantom_job",
    "behavioral_science___policy",
    "black_manosphere", "attention_inequality", "honey_trapping",
    "amity_enmity_complex", "blame", "blame_in_organizations",
    "sunk_cost",                  # sunk_cost_fallacy로 대체됨
    "aesthetic_usability_effect", # UX/디자인
    # 중복 항목
    "anchoring__cognitive_bias_", "anchoring_effect",
    "priming__psychology_", "framing_effect__psychology_",
    "habit", "reciprocity__social_psychology_", "scarcity__social_psychology_",
    # 목록/개요 페이지
    "list_of_cognitive_biases", "social_psychology",
    # 비심리학 주제
    "behavior_imaging", "behavior_informatics",
    "behavioral_urbanism", "barriers_to_pro_environmental_behaviour",
    "intimidation",
}
```

### 통과 기준 (PSYCHOLOGY_KEYWORDS)

아래 키워드 중 하나 이상이 title+body에 포함되어야 통과:

```
psychology, psychological, psycholog,
behavior, behaviour, cognitive, cognition,
brain, neuroscience, neural, mental health,
bias, heuristic, emotion,
memory, perception, personality, motivation,
anxiety, depression, stress, trauma,
self-esteem, consciousness,
therapy, therapist, psychiatry, psychoanalysis,
mindset, prophecy, attitude, tendency, belief
```

### 현재 facts_raw.csv 상태

- 총 116행 → Keep 84, Reject 32
- 정리 후 84개가 영상 생성에 사용 가능

---

## 이미지 수집 기준

### 이미지 필터

다운로드 후 자동 거절 조건:
1. **파일 크기 < 40KB** — 워터마크/아이콘 이미지
2. **혈액(blood-red)** — R>140, G<80, B<80, R-G>80 픽셀 비율 > 12%
3. **살/장기 색상(flesh/gore)** — R>160, G 80~165, B<140, R-G>35 픽셀 비율 > 30%
   - 해부된 뇌, 수술 사진, 장기 사진 등 차단
   - 단, 뇌 일러스트/3D 렌더링/MRI는 통과 (살색이 아니므로)

### 이미지 구조

- **Hook**: `visuals/_hook/` — 일반 심리학/마인드 이미지 (팩트와 완전 분리)
  - 검색어: `human mind abstract`, `psychology thought concept`, `neuroscience brain illustration` 등
- **Facts**: `visuals/{fact_id}/` — 팩트당 10장
  - 검색어 3가지 변형: primary / `{keyword} concept abstract` / `{keyword} psychology human`
  - `img_01.jpg` → 타이틀카드 전용
  - `img_02~10.jpg` → 나레이션 슬라이드 순환

---

## 영상 렌더링 구조

### 화면 구성
- 해상도: 1920×1080 (16:9)
- 레터박스: 상하 5% 검은 바 (시네마틱)
- 텍스트: Poppins Bold (없으면 시스템 폰트 자동 탐색)

### 세그먼트 구조

| 세그먼트 | 내용 |
|---|---|
| Hook | 훅 텍스트 전체 표시 → 이미지 빠른 전환 (호기심 유발) |
| Fact (Part A) | `Fact N: Heading` 텍스트 + img_01 타이틀카드 |
| Fact (Part B) | 이미지 순환 (img_02~10, Ken Burns zoom 효과) |
| Outro | CTA 텍스트 |

### Ken Burns 효과
1.0 → 1.05 slow zoom, 각 이미지 최대 4초 표시 후 전환

### 검정 전환
팩트 사이 0.3초 black frame 삽입

---

## BGM 가이드

### 폴더 구조

```
config/bgm/
  hook/    bgm_01.mp3, bgm_02.mp3, bgm_03.mp3 ...
  facts/   bgm_01.mp3, bgm_02.mp3, bgm_03.mp3 ...
```

### 선곡 로테이션 방식
영상 title의 MD5 해시 기반으로 자동 선택 → 같은 영상은 항상 같은 BGM, 매 영상마다 다른 BGM

### 볼륨 믹싱
- Hook BGM: 8% (나레이션 뒤에서 분위기 조성)
- Facts BGM: 9%

### 분위기 기준

| 구간 | 분위기 | 특징 |
|---|---|---|
| **Hook** | 긴장감·호기심 유발 | 빌드업 있는 시네마틱, 도입부 임팩트, dramatic |
| **Facts** | 집중·ambient | 잔잔하고 반복적, 나레이션 방해 안 함 |

### 검색 키워드

**Hook BGM 검색어:**
- `cinematic tension no copyright`
- `dark ambient buildup music`
- `suspense intro music free`
- `epic dramatic music no copyright`
- `psychological thriller background music`

**Facts BGM 검색어:**
- `calm background music no copyright`
- `ambient study music free`
- `soft piano background no copyright`
- `focus concentration music free`
- `minimal ambient instrumental`

### 무료 소스

| 소스 | 라이선스 | 비고 |
|---|---|---|
| [Pixabay Music](https://pixabay.com/music/) | 완전 무료, 크레딧 불필요 | **추천** |
| [YouTube Audio Library](https://studio.youtube.com) | YouTube 업로드 전용 무료 | Studio에서 다운로드 |
| [Free Music Archive](https://freemusicarchive.org/) | CC 라이선스 (종류 확인) | 일부 CC BY 필요 |
| [Incompetech (Kevin MacLeod)](https://incompetech.com/) | CC BY 3.0 | 설명란 크레딧 필요 |

---

## 썸네일 레이아웃 (4종 자동 로테이션)

영상 title MD5 해시 기반으로 레이아웃 자동 선택.

| 레이아웃 | 스타일 | 참고 |
|---|---|---|
| **A** | 센터 텍스트 + 황금 언더라인 + 뱃지 | 클래식 |
| **B** | 핵심 단어 하나 거대하게 상단 | "EVERYTHING" 스타일 |
| **C** | 좌측 정렬 + 왼쪽 노란 세로 바 | "NIHILISM" 스타일 |
| **D** | 영화적 인용구/문장 센터 | "You shouldn't be alive" 스타일 |

- 배경: visuals/ 에서 가장 큰 파일 사용 (품질 높은 이미지 자동 선택)
- 어둡게 처리 (factor 0.40) + 비네트 효과
- `N FACTS` 뱃지 우측 상단 (노란 배경, 검은 텍스트)
- 폰트: Poppins Bold (config/fonts/ 에 있어야 함)

---

## YouTube 채널 개설 가이드

### Step 1 — Google 계정 준비

- 기존 개인 계정 사용 가능 (브랜드 계정 권장)
- **브랜드 계정 이점**: 여러 관리자 추가 가능, 채널명을 본명과 분리, 나중에 Google 계정 변경해도 채널 유지
- 생성: [myaccount.google.com](https://myaccount.google.com) → 좌측 "브랜드 계정 관리" → 계정 만들기

---

### Step 2 — YouTube 채널 생성

1. [youtube.com](https://youtube.com) 로그인
2. 우측 상단 프로필 → **"채널 만들기"**
3. 채널명 입력: `Brainboda` (또는 원하는 이름)
4. 핸들(handle) 설정: `@Brainboda` — 짧고 기억하기 쉽게

> **채널명 선정 기준**: 영어권 타겟이면 발음하기 쉽고 의미 있는 단어 조합 추천  
> 예) BrainBoda / MindUnlocked / PsychFacts / CogniFlow

---

### Step 3 — 채널 기본 설정

| 항목 | 내용 |
|---|---|
| **채널 설명** | "Weekly psychology facts that change how you see yourself and others. Science-backed insights in under 15 minutes." |
| **채널 아이콘** | 1000×1000px 이상, PNG. 심플한 뇌/마인드 아이콘 |
| **채널 아트(배너)** | 2560×1440px (안전 영역 1546×423px) — 채널 컨셉 표현 |
| **카테고리** | Science & Technology 또는 Education |
| **국가** | 미국 (US) — CPM 높음 |
| **언어** | 영어 |
| **키워드** | psychology, human behavior, mind, cognitive bias, neuroscience, self-improvement |

---

### Step 4 — 채널 수익화 자격 요건 (YPP)

YouTube 파트너 프로그램(YPP) 가입 기준:

| 기준 | 수치 |
|---|---|
| 구독자 | **500명** 이상 (기본 monetization feature) |
| 구독자 (광고 수익) | **1,000명** 이상 |
| 최근 12개월 시청 시간 | **4,000시간** 이상 |
| 또는 Shorts 조회수 | **1,000만 뷰** (90일 이내) |
| 커뮤니티 가이드라인 위반 | 없어야 함 |
| 연결된 AdSense 계정 | 필요 |

> **전략**: 초기에는 Shorts와 메인 영상을 병행 업로드 — Shorts는 알고리즘 노출이 빠르고, 메인 영상은 시청 시간(4,000시간) 축적에 유리

---

### Step 5 — YouTube Data API v3 설정 (업로드 자동화)

```
1. Google Cloud Console 접속
   https://console.cloud.google.com

2. 새 프로젝트 생성
   "Brainboda" 또는 원하는 이름

3. YouTube Data API v3 활성화
   API 및 서비스 → 라이브러리 → "YouTube Data API v3" 검색 → 사용 설정

4. OAuth 2.0 사용자 인증 정보 생성
   API 및 서비스 → 사용자 인증 정보 → + 사용자 인증 정보 만들기
   → OAuth 클라이언트 ID
   → 애플리케이션 유형: 데스크톱 앱
   → 이름: Brainboda Uploader

5. JSON 다운로드
   생성된 클라이언트 ID 우측 ↓ 버튼 → JSON 다운로드

6. 파일 배치
   다운로드한 파일을 client_secrets.json 으로 이름 변경 후
   프로젝트 루트 또는 config/ 폴더에 저장

7. OAuth 동의 화면 설정 (최초 실행 전)
   API 및 서비스 → OAuth 동의 화면
   → 외부 선택 → 앱 이름/이메일 입력 → 저장
   → 테스트 사용자에 본인 Google 계정 추가
```

> **최초 실행 시**: 브라우저가 열리고 Google 계정 인증 요청됨 → 승인하면  
> `token.json` 자동 생성 → 이후 자동 업로드 가능

---

### Step 6 — 채널 운영 체크리스트

```
[ ] Google 계정 / 브랜드 계정 생성
[ ] YouTube 채널 개설 (채널명, 핸들 설정)
[ ] 채널 아이콘 제작 (1000×1000px)
[ ] 채널 배너 제작 (2560×1440px)
[ ] 채널 설명 작성 (영어)
[ ] 카테고리 / 국가 / 언어 설정
[ ] AdSense 계정 연결 (수익화 준비)
[ ] Google Cloud 프로젝트 생성
[ ] YouTube Data API v3 활성화
[ ] OAuth 2.0 credentials 다운로드 → client_secrets.json 저장
[ ] python run.py --type main --skip-upload 로 영상 생성 테스트
[ ] python run.py --type main 으로 첫 업로드 테스트
```

---

### 설명란 자동 생성 포맷 (02_build_script.py)

업로드 시 자동으로 아래 형식의 설명란이 생성됩니다:

```
{영상 제목}

In this video, we explore {n} fascinating psychology facts about human behavior...

⏱️ TIMESTAMPS
0:00 - Introduction
...

📌 Topics covered: {fact_headings}

🎵 Music: Pixabay Music (https://pixabay.com/music/)
License: Pixabay Content License — Free for commercial use, no attribution required.

#psychology #humanbehavior #mindset #cognitivebias #neuroscience
```

---



```bash
# 1. Python 패키지
pip install requests edge-tts moviepy pillow google-api-python-client numpy

# 2. FFmpeg 설치 (macOS)
brew install ffmpeg

# FFmpeg 설치 (Windows)
# https://ffmpeg.org/download.html → PATH 추가

# 3. Poppins 폰트 다운로드
python config/fonts/download_fonts.py

# 4. API 키 설정 (config/channel.py 또는 환경변수)
PIXABAY_API_KEY=your_key    # pixabay.com 무료 가입
PEXELS_API_KEY=your_key     # pexels.com/api 무료 가입

# 5. YouTube Data API v3 설정
# Google Cloud Console → 새 프로젝트
# → YouTube Data API v3 활성화
# → OAuth 2.0 credentials 다운로드
# → client_secrets.json 으로 저장 (repo root 또는 config/)
```

---

## 개발 현황

### ✅ 완료

| 단계 | 파일 | 내용 |
|---|---|---|
| 01 | `01_fetch_facts.py` | Wikipedia facts 수집, seed facts fallback |
| 02 | `02_build_script.py` | 스크립트 생성, 품질 필터, used_facts 트래킹 |
| 03 | `03_tts.py` | edge-tts TTS, ffmpeg concat |
| 04 | `04_fetch_visuals.py` | 이미지 수집 (팩트당 10장, hook 분리, gore 필터) |
| 05 | `05_render_video.py` | MoviePy 렌더링, Ken Burns, 레터박스, BGM 믹싱 |
| 06 | `06_thumbnail.py` | 썸네일 4종 레이아웃 로테이션 |
| 07 | `07_upload.py` | YouTube 업로드, OAuth2, 썸네일 설정 |
| - | `run.py` | 전체 파이프라인, 렌더 실패 시 즉시 중단 |
| - | `clean_facts_csv.py` | CSV 품질 필터 유틸리티 |

### 🔧 진행 중

- **BGM 다중 파일 로테이션** — `config/bgm/hook/`, `config/bgm/facts/` 폴더 기반, title 해시로 선택

### 📋 예정

| 항목 | 비고 |
|---|---|
| BGM 파일 수집 | Pixabay Music에서 hook용 3개 + facts용 3개 이상 다운로드 |
| YouTube 업로드 테스트 | client_secrets.json 설정 후 |

---

## data/ 폴더 관리

### 파일 목록

| 파일 | 용도 | 비고 |
|---|---|---|
| `used_concepts.json` | AI 테마·컨셉 중복 방지 | 같은 주제 재사용 방지 |
| `used_image_urls.json` | 이미지 URL 중복 방지 | 동일 이미지 재수집 방지 |
| `used_shorts_facts.json` | 쇼츠로 발췌된 팩트 기록 | 같은 팩트로 쇼츠 중복 생성 방지 |
| `latest_main_script.json` | 가장 최근 메인 스크립트 | Shorts Actions가 참조 |

> Wikipedia 모드 파일(`facts_raw.csv`, `facts_approved.csv`, `used_facts.json`)은 AI 모드에서 사용하지 않으므로 `.gitignore` 처리됨.

### 사용 이력 초기화 방법

테스트 재시작이나 리셋이 필요할 때:

```bash
# 테마·컨셉 이력 초기화
echo '{"used_themes": [], "used_concepts": {}}' > data/used_concepts.json

# 이미지 이력 초기화
echo '[]' > data/used_image_urls.json

# 쇼츠 팩트 이력 초기화
echo '[]' > data/used_shorts_facts.json

# git에 반영
git add data/
git commit -m "chore: reset usage history"
git push origin <branch>
```

---

## 브랜치

| 브랜치 | 용도 |
|---|---|
| `main` | 안정 버전 |
| `claude/kind-shannon-5j3i8i` | 현재 개발 브랜치 |

---

## 수익화 목표

| 구독자 | 월 수익 (예상) |
|---|---|
| 1만 | $50~150 |
| 5만 | $500~1,500 |
| 10만 | $1,000~3,000 |

> 영어 Psychology/Self-help 카테고리 CPM $3~8 기준
