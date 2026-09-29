# Blackmagician 실시간 촬영 모드

Data Handler에서 촬영 세션에 연결하면 전용 모드를 열고, 앱 서버가 프로젝트별 백그라운드 구독을 유지한다. 화면과 별도 로컬 에이전트 서비스는 원자적으로 저장된 동일한 상태를 읽는다. DataManager/DataHelper의 복제 진행률을 감시하거나 촬영 상태를 백업 성공으로 해석하지 않는다.

## 현재 지원

- 초대 코드: 기존 `/api/events`의 NDJSON을 수신한다. 서버의 주기적 연결 종료 이후에는 같은 자격으로 재접속한다. `/api/join`은 사용자가 연결할 때만 호출한다.
- 세션 ID: 기존 Firestore REST 읽기를 사용한다. 전체 조회가 끝난 뒤 3초 대기 후 다시 조회한다. 이것은 스트림 전송과 달리 폴링이며, 대규모 세션에서는 조회·페이지 처리 시간과 읽기 비용이 늘어난다.
- 네트워크 중단: 마지막 완전한 기록을 유지하고 재접속한다. 매 재접속마다 4종 초기 데이터가 모일 때까지 부분 결과를 공개하지 않는다. `entries`는 전체 교체이므로 과거 수정과 삭제를 반영한다.
- 자격·권한·세션 오류(401/403/404/410): `reauth_required`. 자동 join으로 초대 코드를 다시 소비하지 않는다.
- 종료: `ended`, 이후 메모를 약 15초 간격으로 확인한다. 수신 일시정지와 연결 해제는 진행 중 응답의 세대 식별자를 폐기한다.
- 프로세스 재시작: `live.enabled=true`인 프로젝트만 복원한다. 프로젝트별 파일 잠금으로 여러 앱 프로세스의 중복 구독을 막는다. 앱 서버가 종료된 동안은 수신되지 않으며, 다음 시작 시 전체 상태로 복구한다.
- 질문: 빈 `scene`, 빈 `takeResult`, 사본 간 충돌을 결정적인 규칙으로 탐지한다. 질문 ID는 테이크 키와 필드로 안정적으로 생성한다. 동일한 기록이나 heartbeat가 질문을 중복 생성하지 않는다.
- 로컬 모델: 질의마다 선택한 프로젝트의 최신 저장 상태, 현재 카메라/Script, 전체 기록 수와 결과 집계, 질의 관련 테이크를 전달한다. 문맥 길이에 맞춰 선택한 행을 줄이고 제외한 수를 명시한다. 과거 촬영 설정은 현재 카메라 설정으로 채우지 않는다. 메모는 지시가 아닌 데이터로 처리한다.

물리 카메라부터 클라우드까지의 연결 지연은 Blackmagician의 전송에 달려 있다. Data Handler가 표시하는 수신 시각은 이 Mac이 정보를 받은 시각이며, 카메라 자체의 실시간 연결 보증이 아니다.

## 로컬 API

모든 경로는 `/api/blackmagician` 아래에 있고, loopback·동일 Origin·`X-DIT-Blackmagician` 세션 인증을 요구한다. `/session`에서 앱 내부용 토큰을 가져온다. Blackmagician의 Bearer 자격은 브라우저나 모델에 전달하지 않는다.

| 경로 | 의미 |
| --- | --- |
| `GET /projects/{local_project_id}` | 연결, 최신 스냅샷, 수신 상태, 질문, 로컬 확인 메모, 기능 지원 여부 |
| `POST /projects/{id}/connect` | `mode`, `code`, 선택적 `project_id`; 성공 시 자동 수신 활성화 |
| `POST /projects/{id}/live` | `{ "enabled": true/false }`; 재개 또는 일시정지 |
| `POST /projects/{id}/questions/{question_id}` | `{ "value": "OK", "entry_revision": "..." }`; 원본 버전이 일치할 때 로컬 확인 내용 저장 |
| `POST /projects/{id}/refresh` | 전체 상태 재조회 |
| `POST /projects/{id}/disconnect` | 수신 중지 및 기존 자격 leave 처리 |
| `POST /projects/{id}/review` | 완료 아티팩트 기반 백업 검토 |

`live`는 `enabled`, `status`, `transport`, `revision`, `changed_at`, `last_received_at`, `last_observed_at`, `last_error`, 최근 `activity`를 포함한다. `revision`은 기록 내용이 변할 때 증가한다. `last_received_at`은 heartbeat도 반영하며 `last_observed_at`은 완전한 데이터 수신 시각이다. 35초 넘게 수신하지 못한 활성 연결은 공개 응답에서 `reconnecting` 및 `from_cache=true`로 판정한다.

확인 메모는 다음 정보를 포함한다.

```json
{
  "id": "질문 ID",
  "project_id": "Blackmagician 프로젝트 ID",
  "session_id": "Blackmagician 세션 ID",
  "entry_key": "project/session/takeId",
  "field": "takeResult",
  "value": "OK",
  "expected": "",
  "entry_revision": "확인 전 원본 데이터 해시",
  "source": "operator",
  "status": "local",
  "remote_applied": false,
  "confirmed_at": "ISO 8601"
}
```

`status`: `local`은 로컬에만 저장, `reflected`는 원격에서 같은 값이 관측됨, `conflict`는 원본이 바뀌어 다시 확인 필요, `obsolete`는 원격 테이크 삭제다. `reflected`도 Data Handler가 수정했다는 의미가 아니므로 `remote_applied`는 false다. 409 응답을 받으면 새 질문과 원본 버전을 읽어 확인해야 한다.

## 후속 Blackmagician 스크립터 보조 모드 연결

현재 `capabilities.remote_write=false`다. 이 버전은 Blackmagician 원본에 쓰거나 카메라 제어 명령을 보내지 않는다. 다음 단계에서 Blackmagician 쪽 UI/인증된 제안 API를 만든 뒤 아래 계약을 연결할 수 있다.

1. 현재의 `questions`와 `confirmations`를 제안·확인 근거로 사용한다. 원격 앱에서 로컬 loopback 인증을 우회하지 말고, 명시적인 세션 연결 채널이나 인증된 서버 API를 추가한다.
2. 수정은 `entry_key`, 허용 필드, 제안 값과 **원격에서 검증 가능한 원본 버전**을 함께 전달한다. 현재 `entry_revision`은 Data Handler의 정규화 JSON 해시이므로 Firestore updateTime과 동일하지 않다. 원격 구현에서 같은 해시 규약을 제공하거나 원격 버전 토큰을 추가해야 한다.
3. 원격 트랜잭션은 세션·편집 권한과 원본 버전을 검증하고, 중복 요청 ID로 한 번만 적용한다. 기존 이중 기록 경로가 있으면 함께 처리한다.
4. 적용 ACK와 다시 수신한 기록으로 적용 여부를 확정한다. 충돌·삭제·권한 거부는 사용자에게 보인다. 자동 적용 여부는 Blackmagician의 보조 모드 설정으로 결정한다.

현재의 로컬 확인 메모는 작업 준비 구조이며, 운영 원격 수정 API가 구현됐다는 뜻이 아니다.

## 저장과 검증

`.pipeline/blackmagician/{local_project_id}/state.json`에 0600 권한으로 상태를 원자 저장한다. 재연결 시 동일 세션의 확인 메모를 유지한다. 교체·해제 전에 `history/{session_hash}.json`에 해당 세션의 마지막 공개 상태와 확인 메모를 보존한다. 자격은 history에 포함하지 않는다. 최근 activity는 100개로 제한하며 전체 감사 이벤트 로그를 대체하지 않는다.

자동 테스트: `orchestrator/tests/test_blackmagician_live.py`. 실제 Blackmagician 원본 API + 로컬 Firestore 에뮬레이터 + Chrome 검증은 `.superloopy/evidence/frontend/blackmagician-live/`에 있다. 로컬 모델 자연어 응답 근거는 `.pipeline/blackmagician-live-qa/natural-agent-proof.json`에 있다. 운영 Firebase와 물리 카메라 검증은 별도 현장 확인 대상이다.
