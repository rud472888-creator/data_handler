# 영상 QA (작업 완료 후 시각 검사)

기존 Data Handler 작업(복제·체크섬 검증·DataHelper 보고서)이 끝난 뒤, **검증된 복제본**의 영상 프레임을
로컬 `Qwen/Qwen3.5-4B`가 실제 이미지로 보고 "사람이 확인해야 할 곳"을 찾아 증거 이미지가 포함된 HTML 보고서로
남기는 별도 단계입니다. 의심 사항일 뿐 결함 확정·납품 합격 판정이 아니며, 기존 "에이전트 검토"(완료 JSON을
검토하는 기능)와는 이름·상태·산출물이 모두 분리되어 있습니다.

## 흐름

```
기존 작업 완료 (DataHelper worker 종료 처리 / cli continue-* / watcher / 복제 전용 모드의 복제 완료)
  → schedule_visual_qa()  (멱등, orchestrator/visual_qa/scheduler.py)
  → .pipeline/runs/<run_id>/visual_qa/<qa_id>/  manifest.json → worker 프로세스
  → 복제본 clip 디코딩(PyAV, 순차·bounded queue) → 프레임마다 새 컨텍스트로 Qwen3.5-4B 분석
  → frames.jsonl(프레임별 journal) → events(의심 구간) → findings.json → report.html
```

* 입력은 `blackmagician/manifest.json`(DataManager manifest)의 **verified replica_results**에서만 얻습니다.
  경로·파일명을 디스크에서 추측하지 않고, 원본 카드로 되돌아가지 않습니다. 같은 클립이 여러 복제본에 있으면
  첫 번째 사용 가능한 복제본 하나만 검사하고 `replica_used`에 기록합니다. 복제본이 사라지거나 크기가 바뀌면
  다른 검증된 복제본으로 전환(기록됨)하거나 `input_unavailable`로 끝납니다.
* 백업 검증이 끝나지 않았거나(`replicas_complete != true`) manifest/복제본 연결이 없으면
  `visual_qa/blocked.json`만 남기고 아무 파일도 검사하지 않습니다.
* 기존 DataHelper 보고서가 실패했어도 백업 검증이 완료되었으면 QA를 별도로 시도합니다. 백업·기존 보고서·QA
  상태는 서로 독립이며 QA는 `state.json`/`datamanager.done.json`을 건드리지 않습니다.

## 완료 후 QA 연결 지점

| 경로 | 위치 |
| --- | --- |
| DIT 앱/CLI `start` → DataHelper worker | `orchestrator/datahelper_worker.py::_finalize` (최종 리포트 처리 뒤, 실패해도 호출) |
| 복제 전용 모드 | `orchestrator/datamanager_worker.py::run_datamanager` |
| Hermes/CLI 후속 처리 | `orchestrator/cli.py::continue_datahelper`, `continue_datamanager` |
| 로컬 에이전트 watcher | `orchestrator/watcher.py::_handle_artifact` |
| 수동(앱/CLI) | `POST /api/library/cards/{run_id}/visual-qa`, `visual-qa start` |

모두 같은 `schedule_visual_qa()`를 호출합니다. 식별자는 `(run_id, 입력 revision, 분석 설정)`의 해시이고
`schedule.lock`(flock)으로 직렬화되므로 중복 이벤트·앱/CLI/수집기 동시 실행에도 worker는 하나만 뜹니다.
worker는 `worker.lock`을 실행 내내 잡고 있어 죽은 worker(`running`인데 lock이 비어 있음)를 식별해 재개합니다.
앱 시작 시 `recover_orphans()`가 **중단된** QA만 재개하며 기존 기록 전체를 재검사하지 않습니다.
동시에 하나의 QA만 실행됩니다(`visual_qa.slot.lock`).

옵션: 프로젝트 단위 "완료 후 영상 QA 자동 실행"(앱 우측 패널 체크박스, `project.visual_qa`)이 새 카드의
`request.json`에 `visual_qa: true`로 복사됩니다. CLI는 `start --visual-qa`. 기존 완료 작업은 자동 재검사되지 않으며
앱에서 카드를 선택해 "영상 QA 시작"으로만 실행합니다.

## 설치와 실행 (Apple Silicon macOS)

추론 의존성은 앱/백업 환경과 분리된 venv에 설치합니다.

```sh
./script/setup_visual_qa_env.sh                       # ~/Library/Application Support/Data Handler/visual-qa/venv
QA_PY="$HOME/Library/Application Support/Data Handler/visual-qa/venv/bin/python"
# 1) 모델 설치: 명시적인 단계이며 네트워크가 필요합니다. 실행 중에는 다운로드/변환을 하지 않습니다.
PYTHONPATH=. "$QA_PY" -m orchestrator.cli visual-qa install-model            # Qwen/Qwen3.5-4B, revision은 설치 시점 커밋 해시로 기록
#    이미 받은 가중치 등록(오프라인):  install-model --local-path DIR --revision <hash>
#    MLX 양자화 모델 사용:            install-model --source-repo <repo> --quantization <방식> --derived-from Qwen/Qwen3.5-4B
# 2) 실제 모델 smoke test (이미지 입력 확인 → 정상/이상 합성 클립 → 보고서)
PYTHONPATH=. "$QA_PY" -m orchestrator.cli visual-qa smoke --output ./smoke-out
# 3) 수동 QA / 상태 / 보고서 재생성
python -m orchestrator.cli visual-qa start --run-id <run_id> [--foreground] [--new-revision]
python -m orchestrator.cli visual-qa start --run-id <run_id> --foreground --max-frames-per-clip 48   # 개발용 제한: 결과는 "제한 범위"로 표시
python -m orchestrator.cli visual-qa status --run-id <run_id>
python -m orchestrator.cli visual-qa report --run-id <run_id> --qa-id <qa_id>    # journal에서 findings/report만 재생성
```

worker는 `DATA_HANDLER_VISUAL_QA_PYTHON` 또는 위 venv의 python으로 실행됩니다(없으면 현재 python).
기본 모델 등록 위치는 `~/Library/Application Support/Data Handler/visual-qa/models/model-install.json`입니다.
테스트처럼 `DATA_HANDLER_VISUAL_QA_HOME`을 별도 경로로 지정했다면, 자동 QA를 시작하는 앱 프로세스에도
같은 환경 변수를 적용해야 worker가 동일한 등록 정보를 찾습니다. 터미널의 수동 검사에만 적용하면 자동 검사는
`model_not_installed`로 막힐 수 있습니다. 일반 앱에서는 위 기본 위치에 설치·등록하는 편이 간단합니다.
모델은 앱 번들 밖(`visual-qa/models`)에 있고, 로드는 `HF_HUB_OFFLINE=1`로 로컬 경로에서만 합니다.
모델이 없거나 플랫폼/런타임이 맞지 않으면 QA는 `blocked`와 구체적 사유(`model_not_installed`,
`unsupported_platform`, `runtime_missing` …)로 끝나며 어떤 프레임도 "정상"으로 기록하지 않습니다.
외부 API로의 fallback은 없습니다.

## 추론 방식

* 백엔드: MLX-VLM(`mlx-vlm==0.7.4`, Qwen3.5 지원 확인). 프로세스당 모델 1회 로드, 프레임마다 시스템+사용자
  2턴짜리 **새 컨텍스트**, 이미지는 PIL 객체로 `generate(image=[...])`에 전달. 도구 없음.
* thinking 비활성화: 채팅 템플릿 `enable_thinking=False` + `generate(enable_thinking=False)`. 렌더링된 프롬프트
  꼬리에 빈 `<think></think>` 블록이 있는지 `describe()["thinking_check"]`에 기록. 출력에 `<think>`가 섞이면 제거하고
  경고를 남기며, 닫히지 않으면 실패로 처리합니다.
* 구조화 출력: MLX-VLM 라이브러리 호출 경로에는 JSON Schema 제약 디코딩이 없어(서버 전용) 프롬프트 JSON 지침 +
  엄격한 스키마 검증(`schema.py`)을 씁니다. 파싱 실패·`finish_reason=length`(잘림)·타임아웃·OOM은 분석 실패이고
  제한 횟수(`max_retries=2`, OOM은 1회)만 재시도합니다. 응답이 멈추면(timeout) MLX 호출은 취소할 수 없으므로 그 run의
  백엔드를 폐기하고 남은 클립은 `not_run`으로 남깁니다.
* 좌표: 모델은 본 이미지를 0~1000 격자로 나눈 bbox/point만 반환하고, 프로그램이 범위·형식을 검증한 뒤
  모델 입력 px와 원본 px로 변환합니다. 잘못된 값과 화면 전체 박스는 버리고 `null`로 둡니다(임의 박스 없음).
* 파일명·프레임 번호·PTS·시각은 모델이 아니라 디코더/manifest 값을 결합합니다.

## 검사 범위·프레임

* 기본 `full_frames`: 디코딩되는 모든 프레임을 모델에 보냅니다(샘플링 없음). `--start-frame/--end-frame/
  --max-frames-per-clip/--max-clips`는 개발용이며 실행 결과가 `limited`로 저장·표시됩니다.
* `frame_index`는 디코더 출력 순서, 시각은 프레임 PTS×time_base에서 클립 시작 기준으로 계산한 **클립 상대 시각**입니다.
  PTS가 없으면 시각 미상으로 남깁니다(frame_index/FPS 추정 없음). 소스 타임코드는 표시하지 않습니다.
* 디코딩 종료(EOF 도달)와 분석 완료는 분리해 기록합니다. 컨테이너가 알리는 프레임 수와 실제 디코딩 수가 다르면
  `declared_mismatch`로 표시합니다.
* 모델 입력은 종횡비를 유지한 축소(`model_max_side`, 기본 1024)이며 크롭/LUT/톤매핑은 하지 않습니다.
  의심 프레임은 원본 해상도 JPEG 증거와 표시 이미지·원본 크롭을 저장하되 "원본 해상도 전체를 검사했다"고 표시하지 않습니다.
* 지원 형식: PyAV/FFmpeg가 디코딩하는 일반 영상(mp4, mov, m4v, mxf, avi, mkv, mts/m2ts, webm, mpg).
  BRAW/R3D/ARRIRAW/CRM/CINE/N-RAW는 연속 프레임 어댑터가 없어 `unsupported`로 보고합니다(대표 프레임 추출은 전수 QA가 아님).
  그 외 확장자(사이드카·오디오 등)는 검사 대상에서 제외하고 개수만 기록합니다.

## 산출물 `visual_qa/<qa_id>/`

`manifest.json`(입력·설정·모델 정보) · `state.json` · `frames.jsonl`(프레임별 journal, 원본 모델 출력·시도·시간 포함) ·
`clips.jsonl` · `errors.jsonl` · `findings.json`(그룹화된 event + 클립별 범위) · `summary.json` · `report.html` · `evidence/`.
재검사(`--new-revision`)는 `<qa_id>-rN` 새 디렉터리를 만들고 이전 결과를 덮어쓰지 않습니다. 재개 시에는 같은
`analysis_fp`(설정+모델)의 완료 프레임만 재사용하고, 실패 프레임은 다시 시도하며, 모델이 바뀌었으면
`model_changed`로 멈춥니다. JSONL의 잘린 마지막 줄은 재개 시 복구합니다.

## 현재 한계

* 이 문서의 실제 모델 검증 결과는 `docs/visual-qa-validation.md`를 참고하세요.
* 1픽셀 결함, 프리즈·플리커·프레임 드롭 판정은 지원하지 않습니다(단일 프레임 분석, 연속 프레임에서 관찰되면 event에 표시).
  픽셀 전용 검사기는 `category=pixel_anomaly` 자리에 후속 연결할 수 있습니다.
* 요약 PDF는 만들지 않았습니다(HTML이 필수 산출물).
* 소스 타임코드 표시, RAW 연속 프레임 디코딩, 복제본 체크섬 재검증은 포함하지 않았습니다(크기만 확인).
