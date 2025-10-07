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

# Figma 템플릿 기반 생성
uv run cardnews figma \
  --title "오늘의 명언" \
  --subtitle "성공을 위한 첫 걸음" \
  --business-name "나노바나나" \
  --image-prompt "따뜻한 아침 햇살" \
  --figma-file-key YOUR_FIGMA_FILE_KEY \
  --figma-frame-id 123:456 \
  --figma-title-node 123:789

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

## Figma 통합

- `FIGMA_API_KEY` 환경 변수를 설정하면 Figma API를 통해 지정한 프레임을 렌더링하고, 텍스트 영역 좌표를 자동으로 불러옵니다. (기존 `FIGMA_ACCESS_TOKEN`도 하위 호환용으로 인식됩니다.)
- `cardnews figma` 명령은 기본 설정(`figma.file_key`, `figma.frame_id`, `figma.nodes.*`/`figma.names.*`)을 활용하며, 필요 시 CLI 옵션으로 덮어쓸 수 있습니다.
- 상호명(`--business-name`) 입력을 지원하며, 배경 이미지 프롬프트에는 기본적으로 `실사스러운 이미지를 생성` 요구사항이 자동으로 추가됩니다.
- Gemini 통합 모델 기본값은 `nanobanana`(텍스트)와 `nanobanana-image`(이미지)이며, 내부적으로 Google Gemini 모델로 매핑됩니다.

### 설정 방법 요약

1. **Figma Personal Access Token 발급** → Figma 웹 앱에서 `Settings > Account > Personal access tokens`로 이동해 새 토큰을 만들고 `FIGMA_API_KEY` 환경 변수에 저장합니다.
2. **파일 키 확인** → Figma 파일 URL의 `/file/<FILE_KEY>/` 부분에서 `<FILE_KEY>`를 복사해 `figma.file_key`에 입력합니다.
3. **프레임 ID 확보** → 템플릿으로 사용할 프레임을 선택한 뒤 `Share > Copy link`를 사용하면 URL 끝의 `?node-id=<FRAME_ID>` 값을 얻을 수 있습니다.
4. **텍스트 슬롯 지정** → 레이어 ID를 알고 있다면 `Copy link`의 `node-id`를 `figma.nodes.*`에 입력하고, 어렵다면 프레임 안에서 보이는 레이어 이름을 `figma.names.*`에 그대로 적으면 됩니다. 이름과 ID 중 하나만 있어도 동작합니다.
5. **설정 저장** → 루트의 `config.yaml`에 아래와 같은 섹션을 추가하거나 `cardnews config --set figma-title-name "타이틀"`처럼 명령으로 값을 등록합니다.

```yaml
figma:
  file_key: "ABC123xyz"
  frame_id: "12:345"
  nodes:
    title: "34:567"
    subtitle: "34:890"
    business: "34:901"
  names:
    title: "메인 타이틀"
    subtitle: "서브텍스트"
    business: "브랜드명"
  scale: 1.5 # 선택 사항: Figma 렌더링 배율
  format: "png"
```

필요 시 `cardnews figma --figma-file-key ...` 형식으로 CLI 옵션을 사용해 개별 실행마다 값을 덮어쓸 수도 있습니다.

## 요구 사항

- Python 3.8+
- Pillow, Click, PyYAML, google-genai (자동 설치)

## 개발 팁

```bash
# 코드 스타일 검증
python -m compileall cardnews
```

필요한 폰트 파일은 `cardnews config --set` 명령으로 등록하고, 배경 이미지는 `assets/` 디렉토리를 활용해 정리할 수 있습니다.
