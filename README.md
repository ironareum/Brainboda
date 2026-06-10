# Brainboda — YouTube Automation Pipeline

> **Psychology · Human Behavior · Success Mindset**
> Channel: Brainboda | Language: English | Platform: YouTube

---

## 프로젝트 개요

Wikipedia 심리학 facts를 자동으로 수집해서 영어 YouTube 영상(메인 + Shorts)을 완전 자동 생성·업로드하는 Python 파이프라인.

**비용 원칙: 완전 무료** — ElevenLabs 등 유료 API 사용 금지.

---

## 기술 스택

| 역할 | 도구 |
|---|---|
| Facts 수집 | Wikipedia REST API (영어판) |
| TTS | edge-tts (`en-US-GuyNeural` / `en-US-JennyNeural`) |
| 이미지 | Pixabay API + Pexels API |
| 영상 렌더링 | FFmpeg + MoviePy |
| 자막 | openai-whisper (로컬) |
| 썸네일 | Pillow |
| 업로드 | YouTube Data API v3 |
| 스케줄 | Windows Task Scheduler |

---

## 폴더 구조

```
Brainboda/
├── config/
│   └── channel.py              ← 채널 설정 (TTS 보이스, 카테고리, 경로 등)
│
├── data/
│   ├── facts_raw.csv           ← Wikipedia에서 수집된 원본 facts (누적 append)
│   ├── facts_approved.csv      ← 검수 완료된 facts (선택적 수동 검수)
│   └── used_facts.json         ← 영상에 사용된 fact ID 트래킹 (중복 방지)
│
├── pipeline/
│   ├── 01_fetch_facts.py       ← Wikipedia EN → 심리학 facts 수집
│   ├── 02_build_script.py      ← facts 선택 → 영어 스크립트 JSON 생성
│   ├── 03_tts.py               ← edge-tts → MP3 나레이션
│   ├── 04_fetch_visuals.py     ← Pixabay/Pexels → 이미지 수집
│   ├── 05_render_video.py      ← FFmpeg → MP4 렌더링
│   ├── 06_thumbnail.py         ← Pillow → 썸네일 생성
│   └── 07_upload.py            ← YouTube Data API → 업로드
│
├── output/                     ← 생성된 영상 임시 저장
├── logs/                       ← 실행 로그 (단계별 타임스탬프)
├── run.py                      ← 전체 파이프라인 진입점
└── README.md
```

---

## CLI 사용법

```bash
# 메인 영상 생성 + 업로드
python run.py --type main

# Shorts 생성 + 업로드
python run.py --type short

# 로컬 렌더링만 (업로드 없음, 테스트용)
python run.py --type main --test

# 생성만, 업로드 스킵
python run.py --type main --skip-upload

# 특정 주제로 수집
python run.py --type main --topic "manipulation"
```

---

## 데이터 흐름

```
[수집 단계]
Wikipedia REST API
    → facts_raw.csv (누적 append, 삭제 안 함)
    → used_facts.json으로 중복 ID 필터링

[생성 단계]
facts_raw.csv
    → (used_facts.json에 없는 것 중 랜덤 선택)
    → 메인: 10개 facts / Shorts: 3개 facts
    → 선택 즉시 used_facts.json에 마킹
    → script_{timestamp}.json 생성
    → MP3 → 이미지 → MP4 → 썸네일 → 업로드
```

### facts_raw.csv 수집 주기

- `run.py` 실행 시 **매번 자동으로 01_fetch_facts.py 실행**
- Pool이 충분하면 (사용 가능한 facts ≥ 10개) Wikipedia 재수집 스킵
- Pool 부족 시 자동으로 추가 수집 (기본 100개씩)
- 수동 수집: `python pipeline/01_fetch_facts.py --limit 100`

---

## 스크립트 구조 (메인 영상)

```
[인트로 훅 — 5초]
"Did you know that [충격적인 심리 사실]? Stay until the end —
 because fact #3 will completely change how you see people."

[팩트 1~10 — 각 30~40초]
"Fact N: [제목]
 [2~3문장 설명. Wikipedia 출처 기반.]
 This means that [실생활 적용 1문장]."

[아웃트로 CTA — 10초]
"Which fact surprised you most? Comment below.
 Subscribe for more psychology facts every week."
```

---

## 개발 현황

### ✅ 완료

#### 1단계 — `pipeline/01_fetch_facts.py` (2026-06-10)

Wikipedia 영어판 심리학 카테고리 facts 자동 수집 후 `facts_raw.csv`에 저장.

**구현 내용:**
- Wikipedia REST API (`/api/rest_v1/page/summary/`) + Action API 순서로 시도
- 실패 시 내장 seed facts 30개로 자동 fallback (오프라인 환경 대응)
- `used_facts.json` 기반 중복 ID 자동 스킵
- `facts_raw.csv`에 누적 append (기존 데이터 유지)
- CLI: `--topic [키워드]`, `--limit [숫자]`, `--offline`

**테스트 결과:**
```bash
python pipeline/01_fetch_facts.py --offline --limit 30
# → 30개 facts 수집 완료 → data/facts_raw.csv 저장
```

**현재 facts_raw.csv:** 30개 facts (Cognitive Bias, Dunning-Kruger, Bystander Effect 등)

---

### 🔄 진행 예정

#### 2단계 — `pipeline/02_build_script.py`

`facts_raw.csv`에서 facts 10개를 선택하여 영어 스크립트 JSON을 생성.

**구현 예정 내용:**
- `used_facts.json`에 없는 facts 중 랜덤 10개(또는 3개) 선택
- YouTube 제목 자동 생성 (훅 패턴 템플릿 적용)
  - `"10 Psychological Facts That Will Change How You See People"`
  - `"7 Psychological Tricks Manipulators Use On You Every Day"`
- 나레이션 포맷: `"Fact N: [제목]. [body]. This means that [실생활 적용]."`
- YouTube 설명란 텍스트 자동 생성
- 해시태그/태그 자동 생성
- 선택된 fact IDs → `used_facts.json`에 즉시 마킹
- 출력: `output/script_{timestamp}.json`

**출력 JSON 구조:**
```json
{
  "type": "main",
  "title": "10 Psychological Facts That Will Blow Your Mind",
  "hook": "Did you know your brain makes 35,000 decisions a day...",
  "facts": [
    { "n": 1, "heading": "Cognitive Bias", "narration": "Fact 1: ...", "duration_est": 35 }
  ],
  "outro": "Which fact surprised you most? Comment below...",
  "description": "YouTube 설명란 텍스트",
  "tags": ["psychology", "human behavior", "mind tricks"]
}
```

#### 3단계 — `pipeline/03_tts.py`
edge-tts (`en-US-GuyNeural`) → 스크립트 JSON을 MP3 나레이션으로 변환

#### 4단계 — `pipeline/04_fetch_visuals.py`
Pixabay + Pexels API → 심리학/뇌/사람 이미지 수집

#### 5단계 — `pipeline/05_render_video.py`
FFmpeg + MoviePy → 이미지 슬라이드 + 나레이션 MP3 → MP4

#### 6단계 — `pipeline/06_thumbnail.py`
Pillow → YouTube 썸네일 (1280×720) 생성

#### 7단계 — `pipeline/07_upload.py`
YouTube Data API v3 → 자동 업로드

#### 8단계 — `run.py`
전체 파이프라인 연결 + CLI 플래그 처리

---

## 사전 준비 (최초 1회)

```bash
# 1. Python 패키지 설치
pip install requests edge-tts moviepy pillow openai-whisper google-api-python-client

# 2. FFmpeg 설치 (Windows)
# https://ffmpeg.org/download.html → 환경변수 PATH에 추가

# 3. API 키 설정 (config/channel.py 또는 환경변수)
PIXABAY_API_KEY=your_key       # pixabay.com 무료 가입
PEXELS_API_KEY=your_key        # pexels.com/api 무료 가입

# 4. YouTube Data API v3 credentials
# Google Cloud Console → 새 프로젝트 → YouTube Data API v3 활성화
# → OAuth 2.0 credentials 다운로드 → client_secrets.json으로 저장
```

---

## 브랜치 전략

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
