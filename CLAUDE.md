# Brainboda — Claude 작업 컨텍스트

## 프로젝트 개요
Brainboda는 완전 자동화 YouTube 심리학 채널 파이프라인입니다.
AI 스크립트 생성 → TTS → 이미지 수집 → 영상 렌더링 → 썸네일 → YouTube 업로드까지 코드 한 줄로 실행.

## 채널 목표 (흔들리지 말 것)
- **채널명**: Brainboda
- **콘텐츠**: 심리학 · 인간 행동 · 성공 마인드셋 (영어)
- **최종 목표**: YouTube 수익화 (YPP: 구독자 1,000명 + 시청 4,000시간)
- **장기 목표**: 심리학 외 뇌과학, 경제, 우주 등 카테고리 확장 (재생목록별 관리)

## 업로드 전략 (절대 기준)

### 콘텐츠 구조
- **메인 영상**: 10 facts, 8-12분, 주 2회 (화/목)
- **쇼츠**: 메인 영상에서 가장 임팩트 있는 팩트 1개 발췌, 주 4회 (월/수/금/토)
- **쇼츠는 반드시 메인 영상에서 발췌** — 별도 주제 X, 채널 정체성 통일 + "전체 영상 보러오기" 유도

### 업로드 스케줄
- 메인: 화요일, 목요일
- 쇼츠: 월/수/금/토
- **같은 날 메인+쇼츠 절대 금지** — 알고리즘이 채널을 Shorts 채널로 분류함
- 공개 시간: **20:00 UTC (오후 3시 EST)** — 미국 직장인 퇴근 후 피크타임

### 알고리즘 전략
- 쇼츠로 빠르게 구독자 확보 → 메인으로 수익 창출
- Phase 1 (1-3개월): 메인 주2 + 쇼츠 주4로 채널 정체성 확립
- Phase 2 (1K 구독 이후): 메인 유지 + 쇼츠 주3으로 줄이고 퀄리티 집중
- 첫 24-48시간 클릭률/완료율이 추천 여부 결정 → 초기 트래픽 유입 중요

### 수익 구조
- 메인 영상 CPM: $3-8 (쇼츠 $0.03-0.05와 비교 불가)
- 쇼츠는 수익보다 구독자·노출 목적
- 재생목록: "How Your Mind Works" (ID: PLAs3NOlOTcp0)

## 기술 스택
- Python 3.10, MoviePy, edge-tts, Pillow, ffmpeg
- Claude Haiku (claude-haiku-4-5) — AI 스크립트 생성 (~$0.008/영상)
- Pixabay/Pexels API — 이미지 수집 (무료)
- YouTube Data API v3 — 업로드 자동화
- GitHub Actions — 스케줄 자동화 (예정)

## 파이프라인 구조
```
01_fetch_facts.py   — Wikipedia 크롤링 (Wikipedia 모드 시)
02_build_script.py  — AI 스크립트 생성 (--ai 플래그)
03_tts.py           — edge-tts TTS (en-US-GuyNeural)
04_fetch_visuals.py — Pixabay/Pexels 이미지 수집
05_render_video.py  — MoviePy 영상 렌더링
06_thumbnail.py     — Pillow 썸네일 생성 (5개 레이아웃)
07_upload.py        — YouTube 업로드 + 재생목록 추가 + 예약 공개
```

## 주요 실행 명령어
```bash
# AI 모드 풀 파이프라인
python run.py --type main --ai --theme "dark psychology"
python run.py --type short --ai

# 기존 스크립트로 렌더링만 (API 비용 절약)
python run.py --script output/YYYYMMDD_HHMMSS_main/script.json --skip-upload

# 테스트 (팩트 2개만, 업로드 없음)
python run.py --script output/.../script.json --test --skip-upload
```

## 코딩 규칙
- **소스 수정 후 반드시 테스트**: `python -m py_compile`, `python --help`, grep으로 미정의 참조 확인
- API 키는 `.env` 파일 관리 (절대 하드코딩 금지)
- 영상/오디오/이미지는 gitignore (로컬 전용), script.json·thumbnail.jpg는 git 추적
- BGM: `config/bgm/hook/`, `config/bgm/facts/`, `config/bgm/outro/` — 파일명 자유

## 미완성/예정 작업
- [ ] GitHub Actions 자동화 스케줄 (메인 화/목, 쇼츠 월/수/금/토)
- [ ] 쇼츠를 메인 영상에서 발췌하는 로직 (현재는 별도 AI 생성)
- [ ] 스토리 아크 강화 (사실 나열 → 내러티브 흐름)
- [ ] 아웃트로에 로고 삽입
