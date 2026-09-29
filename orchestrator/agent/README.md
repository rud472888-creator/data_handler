# Data Handler 로컬 에이전트

Qwen3.8-27B MLX Q8가 한국어 요청을 작업 계획으로 변환합니다. 원본·복제 위치·프로젝트가 표시된 계획을 확인하면 기존 orchestrator가 복제, 체크섬 검증, DataHelper PDF 생성을 진행합니다. Telegram은 요청과 보고 전달에만 사용하며 접수된 작업은 인터넷 연결 없이 실행됩니다.

## 현재 설치

- Python 환경: 작업 폴더의 `.pipeline/agent-venv`
- 모델: `~/Library/Application Support/Data Handler/models/Qwen3.8-27B-8bit`
- 앱과 공유하는 업무 기록: `~/Library/Application Support/Data Handler/.pipeline`
- 서비스: `com.dit.data-handler.agent` 및 `com.dit.data-handler.inference`
- 로컬 API: `127.0.0.1:8766`, 추론: `127.0.0.1:8767`
- 설정과 인증 토큰: 업무 기록 아래 `agent/config.json`, `agent/telegram-token` (0600)
- MTP: 비활성. 현재 검증 대상은 기본 Q8 decode입니다.

서비스는 사용자 로그인 시 자동 시작합니다. 앱 창을 닫아도 유지되며, Mac 종료나 로그아웃 중에는 동작하지 않습니다. 미디어 worker 수명에 맞춰 idle sleep을 방지합니다. 화면 덮개 닫기나 강제 종료를 막는 기능은 아닙니다.

## DIT 앱의 에이전트 모드

`Data Handler DIT` 왼쪽의 **에이전트**를 열면 같은 로컬 에이전트를 채팅으로 사용할 수 있습니다. 대화는 로컬 SQLite 기록에 저장되며 앱을 다시 열어도 이어집니다.

1. 프로젝트를 고르고 요청을 보냅니다. 첫 요청에서는 프로젝트 이름, 원본, 1개 이상의 백업 경로, 촬영일·카메라가 빠진 항목을 물어봅니다.
2. 경로가 갖춰지면 채팅에 실행 전 확인 카드가 표시됩니다. 카드의 **이 경로로 복제 시작**을 눌러야 복제가 시작됩니다.
3. 실행 뒤에는 완료 artifact와 PDF 링크가 같은 대화에 나타나고, Telegram에도 기존 완료보고 정책에 따라 전달됩니다.

브라우저 화면에는 장기 API 토큰이 전달되지 않습니다. 앱은 루프백 전용 세션 토큰으로 로컬 bridge에 연결하며, 다른 출처의 요청은 거절됩니다. 대화의 후속 요청은 앞선 요청 처리가 끝난 뒤에만 받습니다.

모드 진입과 다시 연결 시 추론 서버에 실제 health 요청을 보냅니다. Telegram 연결 확인은 최근 90초 이내 수신 API 통신 성공을 뜻하며, 계정 등록만으로 연결됐다고 표시하지 않습니다. Telegram의 후속 요청에도 같은 사용자에게서 받은 최근 네 차례의 완료된 대화를 전달합니다. 실행 시작에 실패해도 채팅 결과에는 작업 ID와 확인 필요 상태가 남습니다.

에이전트 모드를 열면 모델 사전 로딩을 요청하고, 화면이 열려 있는 동안 15초마다 연결·모델 준비 상태를 갱신합니다. 모델은 마지막 사용 후 30분 동안 메모리에 유지한 뒤 해제됩니다. 첫 로딩 중 보낸 요청도 순서대로 처리합니다. 모델 응답 제한은 요청당 180초이며 초과 시 복제를 시작하지 않고 재요청 안내를 남깁니다. 앱은 마지막 모드와 선택한 대화를 영구 WebView 저장소에 보관합니다.

현재 지원 업무는 복제 계획, 상태 확인, Blackmagician 촬영 기록 기반 백업 검토, 사용 안내입니다. 완료 기록이 도착하면 복제 근거·DataHelper 보고서·해당 릴의 촬영 기록을 각각 새 세션으로 자동 검토합니다. 결과와 추천 행동은 작업 공간의 **에이전트 검토**에서 확인합니다. [완료 검토 상세](../../docs/completion-agent-reviews.md).

프로젝트에서 세션을 연결하고 동기화한 뒤 “모든 클립이 제대로 백업됐는지 검토해줘” 또는 `/backup-review`로 기존 프로젝트 전체 대조도 요청할 수 있습니다. 파일별 완료 체크섬·복제본 존재·크기를 확인하며 근거가 없으면 확인 필요로 남깁니다. 새 프로젝트는 작업 공간에서 먼저 만드세요. 일반적인 Mac 전체 제어나 임의 shell 실행을 수행하는 에이전트는 아닙니다.

## Telegram 사용

1. 본인 계정에서 봇 `@DataHandlerDIT_Lee_0908_bot`을 엽니다.
2. 최초 한 번 로컬 pairing 명령에 표시되는 `/start <일회용 코드>`를 보냅니다. 단순 `/start`로 임의 사용자를 자동 등록하지 않습니다.
3. `/projects`로 프로젝트와 연결 볼륨을 확인합니다. 새 프로젝트는 DIT 앱에서 먼저 만듭니다.
4. 예: `프로젝트 촬영A, 원본 /Volumes/CARD_A, 복제 /Volumes/BACKUP_A 및 /Volumes/BACKUP_B로 복제해줘.`
5. 반환된 계획의 실제 경로를 확인하고 **이 경로로 복제 시작** 버튼 또는 `/approve <계획 ID>`를 사용합니다. 계획은 30분 동안 유효하고 원본 목록이나 디스크 identity가 변경되면 무효입니다.
6. 이후 단계별 승인은 없습니다. `/status`로 에이전트 작업 기록을 확인할 수 있고 종료 시 요약, 근거 문서 및 PDF를 받습니다.

날짜·카메라가 생략되면 AI가 오늘/A를 계획에 제안하며 실행 전 확인할 수 있습니다. 현재 자동 작업은 카드 하나·백업 경로 1개 이상(개수 제한 없음)이며 기본 허용 경로는 `/Volumes`입니다. 다른 루트는 로컬 설정에서 명시적으로 추가해야 합니다.

외부 메시지와 첨부는 Telegram 서버를 거칩니다. 원본 영상은 전송하지 않습니다. 보고 PDF는 로컬에 복사해 둔 뒤 전송하며 실패한 메시지/첨부는 outbox에 남겨 재시도합니다. 첨부당 현재 상한은 49MiB입니다. 원본 PDF가 아직 없거나 상한을 넘으면 해당 파일은 자동 첨부되지 않고 로컬 근거 문서의 원래 경로로 확인해야 합니다. 전송 성공 응답이 유실된 경우 메시지 중복은 발생할 수 있지만 복제 실행을 반복하지 않습니다.

## 로컬 명령

작업 폴더에서 실행합니다.

```sh
export DATA_HANDLER_PIPELINE_ROOT="$HOME/Library/Application Support/Data Handler/.pipeline"
.pipeline/agent-venv/bin/python -m orchestrator.agent status
.pipeline/agent-venv/bin/python -m orchestrator.agent pairing
.pipeline/agent-venv/bin/python -m orchestrator.agent request '현재 작업 상태 알려줘'
```

로컬 request는 작업 ID를 반환합니다. 인증된 `GET /messages/{id}`에서 결과를 읽습니다. 다른 API는 `GET /catalog`, `POST /plans`, `POST /plans/{id}/approve`입니다. 모든 API는 config의 api_token을 Bearer 인증으로 요구하고, 해당 토큰을 모델에 전달하지 않습니다.

재설치:

```sh
uv venv --python 3.12 .pipeline/agent-venv
uv pip sync --python .pipeline/agent-venv/bin/python orchestrator/agent/requirements.lock
.pipeline/agent-venv/bin/python script/install_local_agent.py
```

모델 다운로드는 별도입니다. 정확한 Hugging Face 모델 ID는 `mlx-community/Qwen3.8-27B-8bit`, 확인된 revision은 `815b83c0df8ffd1d1b5244cf75fd6ef14fca9ef9`입니다. 설치된 서비스는 `HF_HUB_OFFLINE=1`과 로컬 경로를 사용합니다. installer는 기존 설정·메신저 토큰을 만들거나 출력하지 않습니다.

중지:

```sh
launchctl bootout "gui/$(id -u)/com.dit.data-handler.agent"
launchctl bootout "gui/$(id -u)/com.dit.data-handler.inference"
```

## 장애와 검증

AI는 허용된 plan/status/help 의도만 제안하고 직접 shell을 실행하지 않습니다. 실행 계획의 소유자, 경로, 원본 목록, 디스크 identity를 서버가 검증합니다. AI가 출력한 approve 명령은 실행하지 않습니다. 중복 메시지는 inbox, 중복 승인은 SQLite claim과 run identity로 차단합니다. 모호한 프로세스 시작 실패는 `needs_review`로 남기며 임의 재시작하지 않습니다.

프로세스 충돌 이후 이미 claim된 작업은 자동 재복제하지 않습니다. worker가 종료됐지만 완료 artifact가 없는 경우에는 로컬 기록을 확인해야 합니다. 자동 취소·재개·디스크 교체·원본 삭제는 이 버전의 기능이 아닙니다.

`python -m pytest orchestrator/tests`는 기존 앱 회귀 검증과 새 allowlist, 중복 요청/승인, 경로 변경, offline outbox, 변조 첨부 방지 및 실제 테스트 영상 복제→검수→PDF 검증을 포함합니다. 사용자 원본의 복제 성공 여부는 실제 작업 완료 artifact로만 판단합니다.
