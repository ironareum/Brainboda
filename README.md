# Brainboda — YouTube Automation Pipeline

> **Psychology · Human Behavior · Success Mindset**
> Channel: Brainboda | Language: English | Platform: YouTube

---

## 프로젝트 개요

Wikipedia 심리학 facts를 자동으로 수집해서 영어 YouTube 영상(메인 10 facts)을 완전 자동 생성·업로드하는 Python 파이프라인.

**비용 원칙: 완전 무료** — ElevenLabs 등 유료 TTS API 사용 금지.

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
│   ├── facts_raw.csv           ← Wikipedia에서 수집된 원본 facts (누적)
│   └── used_facts.json         ← 사용된 fact ID 트래킹 (중복 방지)
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

## 사전 준비 (최초 1회)

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
