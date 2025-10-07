# Cardnews CLI

Nanobanana 스타일의 인스타그램 카드뉴스를 자동 생성하는 파이썬 CLI입니다. JSON, CSV 입력을 지원하며, 필요시 Google Gemini API와 연동할 수 있습니다.

## 빠른 시작

```bash
# 의존성 설치 및 실행 (uv 권장)
uv run cardnews --help
```

`uv run`은 `pyproject.toml`의 의존성을 자동으로 설치한 뒤 명령을 실행합니다. 가상환경을 직접 사용하고 싶다면 `uv venv`로 환경을 만든 뒤 `uv pip install .`을 실행하세요.

## 주요 명령어

```bash
# 단일 카드 생성
uv run cardnews create \
  --title "오늘의 명언" \
  --subtitle "성공을 위한 첫 걸음" \
  --image-prompt "Nanobanana, warm gradient, sunrise" \
  --output result.jpg

# JSON/CSV 입력 파일 활용
uv run cardnews create --input card.json --output result.jpg
uv run cardnews batch --input cards.csv --output-dir ./output

# 브랜드 카드 템플릿 (512x512)
uv run cardnews brand-card \
  --brand-text "브랜드 제목" \
  --title "타이틀 글씨 01" \
  --subtitle "서브타이틀 글씨 01" \
  --footer-text "TEAM AIRA" \
  --background-path ./assets/background.png \
  --output ./output/brand.png

# Gemini로 콘텐츠 생성 (GEMINI_API_KEY 필요)
export GEMINI_API_KEY="YOUR_KEY"
uv run cardnews generate --topic "자기계발" --count 5 --output-dir ./output

# 설정 변경 (기본 폰트 조정)
uv run cardnews config --set font-title "/path/to/Pretendard-Bold.otf"
uv run cardnews config --set font-title-size 80
```

명령 옵션을 생략하고 `uv run cardnews create`만 실행하면 필요한 값들을 순차적으로 질문하며 입력받습니다.

## 설정 위치

- 기본 설정 파일: `./config.yaml` (프로젝트 루트)
- 기존에 `~/.config/cardnews/config.yaml`이 있었다면 자동으로 읽어오지만, 저장 시에는 루트의 `config.yaml`로 기록됩니다.
- `cardnews config --reset`으로 초기화할 수 있습니다.

## 배경 이미지

- `--background-path`로 로컬 이미지를 지정하거나
- `image_prompt`를 제공하면 Gemini Nanobanana 스타일 배경을 생성하고 텍스트를 합성합니다. (프롬프트가 없으면 실행되지 않습니다.)
- Gemini 사용이 불가능한 경우에만 프롬프트 기반 그라데이션 배경을 사용합니다.
- 최종 카드는 항상 1:1 비율(정사각형)로 생성되며 필요 시 중앙 크롭이 적용됩니다.

## Gemini 통합

- `GEMINI_API_KEY` 환경 변수(또는 동일한 값을 담은 `.env`)을 설정하면 Google Gemini API를 사용해 카드 콘텐츠와 Nanobanana 배경 이미지를 생성합니다.
- 키가 없을 경우, 텍스트는 기본 템플릿, 배경은 그라데이션으로 대체됩니다.

## 브랜드 카드 템플릿

- `cardnews brand-card` 명령은 512x512 정사각형 레이아웃을 생성합니다.
- 배경 이미지는 자동으로 중앙 크롭 뒤 리사이즈되며, 필요 시 투명한 흰색 오버레이(기본 alpha 48)로 밝기를 맞춥니다.
- 상단 오른쪽에는 브랜드 텍스트, 왼쪽 하단에는 타이틀/서브타이틀, 오른쪽 하단에는 추가 문구를 배치합니다.
- `--input card.json` 옵션으로 JSON 파일을 읽어 동일한 키(`brand_text`, `title`, `subtitle`, `footer_text`, `background_path`, `output`)를 활용할 수 있습니다.
- `config.yaml`의 `brand_card` 섹션으로 기본 오버레이/그림자 여부와 폰트를 조정할 수 있습니다.

```yaml
brand_card:
  overlay: true           # false로 두면 기본적으로 오버레이를 끄고 시작합니다.
  overlay_alpha: 48       # 명령 인자를 주지 않았을 때 사용할 투명도 (0~255)
  shadow: false           # true로 두면 기본값이 그림자 포함으로 바뀝니다.
  fonts:
    brand:
      path: Pretendard-Regular.otf
      size: 24
    title:
      path: Pretendard-Bold.otf
      size: 72
    subtitle:
      path: Pretendard-Regular.otf
      size: 42
    footer:
      path: Pretendard-Regular.otf
      size: 28
```

설정에 값을 넣지 않으면 내부 기본값(캔버스 크기에 비례하는 크기)이 사용됩니다.

## 요구 사항

- Python 3.8+
- Pillow, Click, PyYAML, google-genai (자동 설치)

## 개발 팁

```bash
# 코드 스타일 검증
python -m compileall cardnews
```

필요한 폰트 파일은 `cardnews config --set` 명령으로 등록하고, 배경 이미지는 `assets/` 디렉토리를 활용해 정리할 수 있습니다.
