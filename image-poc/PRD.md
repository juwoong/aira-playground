# 인스타그램 카드뉴스 자동 생성 CLI 도구 개발

## 프로젝트 개요

Nanobanana 스타일의 배경 이미지를 생성하고, 그 위에 타이틀/서브타이틀 텍스트를 입혀서 인스타그램 사이즈 카드뉴스를 자동 생성하는 CLI 도구를 만들어주세요.

## 기술 스택

- Python 3.8+
- Pillow (텍스트 렌더링 및 이미지 합성)
- Google Gemini API (배경 이미지 생성 프롬프트 처리 및 텍스트 최적화)
- Click 또는 argparse (CLI 인터페이스)
- requests (이미지 다운로드, 필요시)

## 핵심 기능

### 1. CLI 명령어 구조

```bash
# 기본 사용법 (직접 입력)
cardnews create \
  --title "오늘의 명언" \
  --subtitle "성공을 위한 첫 걸음" \
  --image-prompt "peaceful sunset over ocean, warm colors, minimalist" \
  --output result.jpg

# JSON 파일에서 입력
cardnews create --input card.json --output result.jpg

# 배치 생성 (여러 카드뉴스)
cardnews batch --input cards.json --output-dir ./output

# Gemini로 전체 컨텐츠 생성
cardnews generate \
  --topic "자기계발" \
  --count 5 \
  --output-dir ./output

# 설정 관리
cardnews config --set font-title "NanumSquareBold" --set font-subtitle "NanumGothic"
```

### 2. 입력 데이터 구조

**단일 카드뉴스 (card.json):**

```json
{
  "title": "오늘의 명언",
  "subtitle": "성공을 위한 첫 걸음은 시작하는 것",
  "image_prompt": "peaceful sunset over ocean, warm colors, minimalist, soft gradients"
}
```

**배치 생성 (cards.json):**

```json
[
  {
    "title": "첫 번째 카드",
    "subtitle": "서브타이틀 내용",
    "image_prompt": "abstract colorful background, gradient",
    "output": "card_01.jpg"
  },
  {
    "title": "두 번째 카드",
    "subtitle": "또 다른 서브타이틀",
    "image_prompt": "minimalist geometric patterns, pastel colors",
    "output": "card_02.jpg"
  }
]
```

**CSV 형식도 지원:**

```csv
title,subtitle,image_prompt,output
오늘의 명언,성공을 위한 첫 걸음,peaceful sunset,card_01.jpg
내일의 희망,새로운 시작,bright morning sky,card_02.jpg
```

### 3. 필수 구현 요소

**이미지 생성 파이프라인:**

1. **배경 이미지 생성 (Gemini API 활용):**

   - `image_prompt`를 Gemini Imagen API 또는 연동된 이미지 생성 서비스로 전송
   - 대안: 사용자가 로컬 배경 이미지를 지정할 수 있는 옵션
   - 생성된 배경을 1080x1080 또는 1080x1350으로 리사이즈

2. **텍스트 레이아웃 (Pillow):**

   - **타이틀:**

     - 상단 1/3 영역에 배치
     - 큰 폰트 사이즈 (기본: 72pt)
     - 굵은 폰트 (Bold)
     - 중앙 정렬
     - 자동 줄바꿈 (긴 텍스트 처리)

   - **서브타이틀:**

     - 타이틀 바로 아래 또는 중앙 영역
     - 중간 폰트 사이즈 (기본: 36pt)
     - 일반 또는 Medium 폰트
     - 중앙 정렬
     - 자동 줄바꿈

   - **텍스트 가독성:**
     - 배경이 밝으면 어두운 텍스트, 어두우면 밝은 텍스트
     - 텍스트 뒤에 반투명 박스 또는 그라데이션 오버레이 옵션
     - 텍스트 외곽선/그림자 효과

3. **Gemini API 통합:**
   - 주제만 입력하면 타이틀, 서브타이틀, 이미지 프롬프트 자동 생성
   - 텍스트 길이 최적화 (카드뉴스에 적합한 길이로)
   - 다양한 스타일 지원 (명언, 팁, 질문, 정보 등)

### 4. 파일 구조

```
cardnews/
├── cardnews/
│   ├── __init__.py
│   ├── cli.py           # CLI 인터페이스
│   ├── image.py         # Pillow 이미지 처리
│   ├── layout.py        # 텍스트 레이아웃 계산
│   ├── gemini.py        # Gemini API 연동
│   ├── generator.py     # 배경 이미지 생성
│   ├── config.py        # 설정 관리
│   └── utils.py         # 유틸리티 함수
├── assets/
│   ├── fonts/           # 기본 폰트
│   │   ├── title/       # 타이틀용 굵은 폰트
│   │   └── subtitle/    # 서브타이틀용 폰트
│   └── backgrounds/     # 사전 생성된 배경 (옵션)
├── templates/
│   └── layout_*.json    # 레이아웃 템플릿 설정
├── config.yaml.example
├── requirements.txt
├── setup.py
└── README.md
```

### 5. 주요 기능 상세

**이미지 생성 파이프라인:**

```python
def create_cardnews(
    title: str,
    subtitle: str,
    image_prompt: str,
    output_path: str,
    config: dict
):
    # 1. 배경 이미지 생성/로드
    background = generate_background(image_prompt, config)

    # 2. 배경 리사이즈 (1080x1080)
    background = resize_to_instagram(background)

    # 3. 텍스트 오버레이 추가 (가독성 위해)
    background = add_text_overlay(background, config)

    # 4. 타이틀 렌더링
    background = render_title(background, title, config)

    # 5. 서브타이틀 렌더링
    background = render_subtitle(background, subtitle, config)

    # 6. 저장
    background.save(output_path, quality=95)
```

**레이아웃 계산:**

```python
# 텍스트 자동 줄바꿈
def wrap_text(text: str, font, max_width: int) -> list[str]:
    """텍스트를 최대 너비에 맞게 자동 줄바꿈"""

# 텍스트 위치 계산
def calculate_text_position(
    image_width: int,
    image_height: int,
    text_bbox: tuple,
    position: str = "center"  # top, center, bottom
) -> tuple[int, int]:
    """텍스트의 최적 위치 계산"""
```

**Gemini 컨텐츠 생성:**

```python
def generate_content_with_gemini(
    topic: str,
    style: str = "motivational",
    count: int = 1
) -> list[dict]:
    """
    주제를 받아서 타이틀, 서브타이틀, 이미지 프롬프트 생성

    Returns:
        [
            {
                "title": "...",
                "subtitle": "...",
                "image_prompt": "..."
            }
        ]
    """
    prompt = f"""
    인스타그램 카드뉴스 컨텐츠를 {count}개 생성해주세요.

    주제: {topic}
    스타일: {style}

    각 카드뉴스마다 다음을 생성해주세요:
    1. 타이틀: 임팩트 있고 짧은 제목 (10-20자)
    2. 서브타이틀: 부연 설명 또는 핵심 메시지 (20-50자)
    3. 이미지 프롬프트: 영어로, 배경 이미지 생성을 위한 상세한 프롬프트

    JSON 형식으로 응답해주세요.
    """
```

### 6. 설정 관리 (config.yaml)

```yaml
# 이미지 설정
instagram:
  size: "1080x1080" # 또는 "1080x1350"
  quality: 95

# 폰트 설정
fonts:
  title:
    path: "assets/fonts/title/NanumSquareExtraBold.ttf"
    size: 72
    color: "#FFFFFF"
    stroke_width: 3
    stroke_color: "#000000"

  subtitle:
    path: "assets/fonts/subtitle/NanumGothic.ttf"
    size: 36
    color: "#F0F0F0"
    stroke_width: 2
    stroke_color: "#000000"

# 레이아웃 설정
layout:
  title_position: "top" # top, center, bottom
  title_margin_top: 150
  subtitle_margin_top: 50 # 타이틀 아래 여백
  side_padding: 80
  text_overlay:
    enabled: true
    color: "#000000"
    opacity: 0.3

# Gemini API 설정
gemini:
  api_key: ${GEMINI_API_KEY}
  model: "gemini-pro"
  image_model: "imagen-2" # 배경 생성용

# 출력 설정
output:
  format: "jpg"
  auto_timestamp: true # 파일명에 타임스탬프 추가
  prefix: "cardnews_"
```

### 7. 고급 기능

**템플릿 시스템:**

```bash
# 미리 정의된 레이아웃 템플릿 사용
cardnews create --template minimal --input card.json
cardnews create --template bold --input card.json
cardnews create --template gradient --input card.json
```

**스마트 색상 조정:**

- 배경 이미지의 평균 밝기를 분석
- 자동으로 텍스트 색상 조정 (밝은 배경 → 어두운 텍스트)
- 텍스트 가독성 보장

**배경 이미지 소스 옵션:**

```bash
# Gemini로 생성
--image-source gemini

# 로컬 파일 사용
--image-source local --background-path ./bg.jpg

# URL에서 다운로드
--image-source url --background-url "https://..."

# 사전 정의된 템플릿
--image-source template --template-name "sunset"
```

### 8. 사용성 개선

**진행 상황 표시:**

```
🎨 배경 이미지 생성 중... [████████████████████] 100%
✍️  타이틀 렌더링 중...
✍️  서브타이틀 렌더링 중...
✅ 저장 완료: ./output/cardnews_20241002_153045.jpg
```

**배치 처리 진행률:**

```
카드뉴스 생성 중: 3/10 [████████░░░░░░░░░░░░] 30%
```

**검증 및 에러 처리:**

- 타이틀/서브타이틀 길이 검증 (너무 길면 경고)
- 이미지 프롬프트 유효성 검증
- 폰트 파일 존재 확인
- Gemini API 키 유효성 확인
- 생성 실패 시 재시도 로직

### 9. 예상 사용 시나리오

**시나리오 1: 빠른 단일 생성**

```bash
cardnews create \
  --title "오늘의 명언" \
  --subtitle "시작이 반이다" \
  --image-prompt "sunrise, hope, warm" \
  --output today.jpg
```

**시나리오 2: JSON으로 배치 생성**

```bash
# cards.json 준비
cardnews batch --input cards.json --output-dir ./week1
```

**시나리오 3: AI 전체 생성**

```bash
cardnews generate \
  --topic "건강한 습관 만들기" \
  --style "tips" \
  --count 7 \
  --output-dir ./healthy-habits
```

**시나리오 4: 템플릿 활용**

```bash
cardnews create \
  --input card.json \
  --template gradient \
  --background-path my_background.jpg
```

## 우선순위

**Phase 1 (MVP):**

- [ ] 기본 CLI 구조 (create, batch 명령어)
- [ ] 타이틀/서브타이틀 텍스트 렌더링
- [ ] 로컬 배경 이미지 사용
- [ ] 인스타그램 사이즈 출력 (1080x1080)
- [ ] JSON/CSV 입력 파일 지원
- [ ] 설정 파일 관리

**Phase 2:**

- [ ] Gemini API로 배경 이미지 생성
- [ ] Gemini API로 컨텐츠 자동 생성 (generate 명령어)
- [ ] 스마트 색상 조정 (배경 밝기 분석)
- [ ] 텍스트 오버레이/그림자 효과
- [ ] 진행률 표시

**Phase 3:**

- [ ] 다양한 레이아웃 템플릿
- [ ] 웹 UI (선택사항)
- [ ] 이미지 필터/효과
- [ ] 애니메이션 GIF 생성

## 추가 요구사항

1. **한글 지원**:

   - Nanum 폰트 기본 포함
   - 한글 자동 줄바꿈 처리

2. **에러 처리**:

   - 명확한 에러 메시지
   - 해결 방법 제시
   - Dry-run 모드 지원

3. **문서화**:

   - README에 설치, 설정, 사용 예시
   - 각 명령어별 --help 문서
   - 입력 파일 형식 가이드

4. **테스트**:

   - 텍스트 렌더링 테스트
   - JSON 파싱 테스트
   - 이미지 생성 테스트

5. **패키징**:
   - `pip install cardnews-cli`로 설치 가능
   - 필요한 폰트 자동 다운로드 스크립트

## 예제 출력물

생성된 카드뉴스는 다음과 같은 구조:

```
┌─────────────────────────────┐
│                             │
│    [타이틀: 크고 굵게]        │
│                             │
│  [서브타이틀: 중간 크기]      │
│                             │
│     [Nanobanana 배경]       │
│      [이미지 프롬프트로]      │
│        [생성된 이미지]        │
│                             │
│                             │
└─────────────────────────────┘
```

위 요구사항에 맞춰 완전히 동작하는 CLI 도구를 개발해주세요.
Python의 모범 사례를 따르고, 확장 가능한 구조로 설계해주세요.
