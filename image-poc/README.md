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
  --image-prompt "warm gradient, sunrise" \
  --output result.jpg

# JSON/CSV 입력 파일 활용
uv run cardnews create --input card.json --output result.jpg
uv run cardnews batch --input cards.csv --output-dir ./output

# Gemini로 콘텐츠 생성 (GEMINI_API_KEY 필요)
export GEMINI_API_KEY="YOUR_KEY"
uv run cardnews generate --topic "자기계발" --count 5 --output-dir ./output

# 설정 변경 (기본 폰트 조정)
uv run cardnews config --set font-title "/path/to/Pretendard-Bold.otf"
uv run cardnews config --set font-title-size 80
```

## 설정 위치

- 기본 설정 파일: `~/.config/cardnews/config.yaml`
- `cardnews config --reset`으로 초기화할 수 있습니다.

## 배경 이미지

- `--background-path`로 로컬 이미지를 지정하거나
- 프롬프트만 제공하면 POC 단계에서는 프롬프트 기반 그라데이션 배경을 생성합니다.

## Gemini 통합

- `GEMINI_API_KEY` 환경 변수를 설정하면 Google Gemini API를 사용해 카드 콘텐츠를 자동 생성합니다.
- 키가 없을 경우, 주제 기반의 간단한 기본 콘텐츠가 사용됩니다.

## 요구 사항

- Python 3.8+
- Pillow, Click, PyYAML, google-generativeai (자동 설치)

## 개발 팁

```bash
# 코드 스타일 검증
python -m compileall cardnews
```

필요한 폰트 파일은 `cardnews config --set` 명령으로 등록하고, 배경 이미지는 `assets/` 디렉토리를 활용해 정리할 수 있습니다.
