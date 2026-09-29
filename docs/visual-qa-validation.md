# 영상 QA 검증 기록

작성 환경: Linux x86_64 컨테이너(4 vCPU, 15GB RAM), Python 3.11, PyAV 18.1, Pillow 12.3, numpy 2.4.

## C. 실제 Qwen3.5-4B smoke test — **수행하지 못함**

| 항목 | 결과 |
| --- | --- |
| 막힌 단계 | 모델 다운로드와 MLX 실행 자체 |
| 사유 1 | `huggingface.co`가 이 세션의 송신 프록시 조직 정책으로 차단됨(`CONNECT` 403). 우회하지 않았습니다. |
| 사유 2 | MLX는 Apple Silicon macOS 전용이라 이 Linux x86_64 컨테이너에서는 실행할 수 없습니다. `MlxVlmBackend.check_ready()`가 `unsupported_platform`으로 `blocked` 처리합니다(CLI `visual-qa smoke`도 `blocked (unsupported_platform)`로 종료, 실제 확인함). |
| 확인한 것 | PyPI의 `mlx-vlm==0.7.4` **소스**를 내려받아 `qwen3_5` 모델 모듈, `load()`, `apply_chat_template(..., enable_thinking=...)`, `generate(image=[PIL/경로], enable_thinking=..., max_tokens, temperature)`, `GenerationResult.text/finish_reason/peak_memory`(GB)를 확인하고 그에 맞춰 코드를 작성했습니다. 실제로 실행해 보지는 못했습니다. |
| 실제 모델로 검증되지 않은 것 | Qwen3.5-4B가 이미지를 받는지, thinking이 꺼지는지, 출력 JSON의 준수율, 좌표 정확도, 검출/오탐/누락, 프레임당 추론 시간, 메모리 사용량, 양자화 모델 ID/옵션 |

Mac에서 아래를 실행하면 같은 결과가 `smoke-result.json`과 `report.html`로 남습니다(첫 단계인 "색이 다른 두 이미지에 다른 답이 나오는지" 확인이 실패하면 나머지는 진행하지 않습니다).

```sh
./script/setup_visual_qa_env.sh
PYTHONPATH=. "$HOME/Library/Application Support/Data Handler/visual-qa/venv/bin/python" -m orchestrator.cli visual-qa install-model
PYTHONPATH=. "$HOME/Library/Application Support/Data Handler/visual-qa/venv/bin/python" -m orchestrator.cli visual-qa smoke --output ./smoke-out
```

**이 결과가 나오기 전까지 이 기능을 "실제 모델 검증 완료"로 취급하지 마세요.**

## B. 파이프라인/통합 테스트 (실제 인코딩한 H.264 mp4 + **MOCK** 백엔드)

`orchestrator/tests/test_visual_qa_pipeline.py`, `test_visual_qa_scheduler.py`, `test_visual_qa_app.py`,
`test_visual_qa_backend_cli.py`. mock 응답기는 프레임의 **실제 픽셀 평균**을 보고 답합니다(디코딩된 이미지가 백엔드에
도달함을 검증). 이는 Qwen 검증이 아닙니다. 보고서와 manifest에는 `MOCK` 표시가 남습니다.

다룬 항목: 완료 후에만 시작 / 기존 보고서 실패 후에도 시작 / 백업 미검증 blocked / 옵션 off 시 미실행 / 중복·동시 이벤트
단일 worker / 완료된 QA 재실행 안 함, 새 리비전은 이전 보고서 보존 / 카드별 분리 / 복제본 여러 개를 한 번만 검사 /
복제본 유실·크기 변경 시 다른 검증 복제본으로 전환(기록)·원본 카드로 전환하지 않음 / QA 실패 시 백업·기존 보고서 파일이
바이트 단위로 불변 / 종료된 worker 복구·살아 있는 worker 비복구 / 중간 종료 후 재개(완료 프레임 재사용, 잘린 JSONL 복구) /
실패 프레임만 재시도 / 모델 변경 시 결과 미혼합 / RAW 미지원·비영상 파일 제외 / 잘린 영상 디코드 실패는 partial /
모델 미설치·추론 오류·추론 정지 / 제한 범위가 전체 검사로 표시되지 않음 / 보고서만 재생성 / 보고서 실패가 분석 결과를 잃지 않음 /
원본·복제본 미수정 / 완료 경로 hook(DataHelper worker, cli, watcher) 연결 / 앱 API 토큰·출처·경로 탈출 방어.

또한 실제 앱 서버(uvicorn)와 Chromium(playwright)으로 확인했습니다: 카드 선택 시 "영상 QA" 패널이 "에이전트 검토"와 별도로
표시되고, 보고서가 앱 URL(`/api/library/visual-qa/...`)에서 열리며 상대 경로 증거 이미지가 실제로 로드(naturalWidth 640)되고,
"다시 검사"가 실제 worker 서브프로세스를 띄워 이 Linux에서는 `blocked / unsupported_platform`로 끝나고 기존 완료 리비전은 그대로 남았습니다.

## A. 단위 테스트

`test_visual_qa_schema.py`(스키마·잘못된 JSON·잘림·thinking 블록·좌표 검증/변환·전체 프레임 박스·판정 구분),
`test_visual_qa_events.py`(연속 프레임 그룹화·한 프레임 event 유지·정상/실패 프레임이 연결을 끊음·박스 IoU·카테고리 분리),
`test_visual_qa_report.py`(HTML escape·상대 이미지 경로·0건 문구·제한/MOCK 배너).

## 측정 (비-모델 처리 오버헤드만)

1920×1080 H.264 240프레임(합성, 2.4MB), 모델 없는 mock, 이 컨테이너 1 프로세스:
전체 12.5 s, 그중 demux+디코드 0.12 s, RGB 변환+LANCZOS 축소(1024) 11.7 s(≈49 ms/프레임), 최대 RSS ≈ 140 MB.
디코드 측정은 `decode_only_s`(demux/decode)와 `prepare_s`(RGB 변환·축소)로 분리 저장됩니다.
**측정하지 않은 것**: 실제 모델 추론 시간, 모델 메모리, 실촬영물(고비트레이트 4K 등) 처리량. 전수 검사 시간은 프레임 수에
비례하며 추론 속도에 좌우되므로 예상치를 적지 않습니다.

## 회귀

`python -m pytest orchestrator/tests`: 기준선(내 변경 전)과 동일한 11개 실패가 그대로이며 원인은 환경입니다
(`DataManager`/`DataHelper` 서브모듈 디렉터리가 비어 있음, `ffmpeg` 바이너리 없음). 새로 실패한 테스트는 없습니다.
