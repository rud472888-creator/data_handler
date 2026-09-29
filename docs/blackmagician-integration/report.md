# Blackmagician → Data Handler 연동 조사

조사일: 2026-09-11 KST. Blackmagician은 읽기 전용 조사. 실제 Documents 경로 존재 및 `git rev-parse --show-toplevel` 일치 확인. AGENTS.md의 Desktop 경로는 사용하지 않았다. HEAD는 `0750de0dcec5d5ce6cb20a55ef560638935e40ad`; 작업 트리에 다수 변경과 미추적 파일이 있어 HEAD와 현재 소스, 배포가 동일하다고 간주하지 않는다.

## 결론

- 현재 API로 유효한 웹 토큰에 연결된 세션의 `scriptEntries` 전체 초기 스냅샷을 받을 수 있는 구현이 있다. 실제 인증된 배포 수신 성공은 이번 조사에서 확인하지 못했다.
- `/api/events`는 SSE가 아니라 **application/x-ndjson**이다. 한 줄은 `{type,data,serverTime}` JSON이며 `event:`/`data:` 구분자를 파싱하면 안 된다.
- 장기 운영에는 프로젝트·세션 범위를 검증하는 별도 읽기 API를 권장한다. 영구 기록 `takeRecords`를 세션별로 조회하고, 종료된 세션도 읽을 수 있는 독립적인 읽기 인증이 필요하다.
- 현재 기록으로 컷·테이크 및 클립 존재 대조는 가능하지만, 실제 파일명 일치와 촬영 기록 완전성이 보장되는 것은 아니다. FPS·코덱·해상도의 촬영 당시 클립별 저장은 없다. 기록의 시작/끝 TC는 실제 파일 TC로 비교하면 안 된다.

## 실제 존재하는 API (현재 로컬 소스)

공통 오류는 `{code,message}` JSON. 웹 토큰은 32바이트 랜덤 값을 base64url로 인코딩한 별도 opaque token이며 SHA-256 해시로 `_webSessions`를 찾는다. Firebase ID token/Google OAuth token이 아니다.

| 메서드·경로 | 인증/조건 | 입력·응답 | 근거 |
|---|---|---|---|
| POST /api/join | 초대 코드, 만료·사용횟수·세션 존재·종료 검사 | `{code}` → `{token,projectId,sessionId,deviceName,expiresAt,serverTime,eventsUrl}` | [web/functions/api.mjs:75](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:75>) |
| GET /api/events | Bearer 웹 토큰, 미만료 `_webSessions`, sessionAccess 존재 | NDJSON: camera/script/access/admission/credential/entries/commands/heartbeat/error | [web/functions/api.mjs:118](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:118>), [web/functions/api.mjs:154](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:154>) |
| OPTIONS /api/events | 지정 Origin 허용 검사, 토큰 검사 이전 | 204, CORS 헤더 | [web/functions/api.mjs:61](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:61>) |
| POST /api/approval | 웹 토큰, 존재하는 미종료 세션 | `{requested:true}`, 참여 승인 요청 기록 | [web/functions/api.mjs:142](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:142>) |
| POST /api/leave | 웹 토큰 | `{left:true}`, 토큰 삭제·승인 철회 | [web/functions/api.mjs:128](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:128>) |
| POST /api/command | 웹 토큰 + Host control 승인 + 활성/연결 상태 | `{id,kind,value,expected,sentAt}` → `{id,phase}` | [web/functions/api.mjs:203](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:203>) |
| PATCH /api/script/:takeId | 웹 토큰 + script/control 승인 + 미종료 세션 | `{fields,base}` → `{saved:true}`, current 또는 기록 수정 | [web/functions/api.mjs:231](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:231>) |

`GET /api/sessions/{sessionId}/manifest`는 **미구현 제안**이다. 프로젝트 목록/과거 세션 목록/영구 기록 GET/토큰 갱신 API도 이 라우터에는 없다. GET events의 프로젝트·세션은 요청 파라미터가 아닌 토큰 DB 레코드에 고정된다.

join은 읽기 전용이 아니다. 분당 IP 해시 제한 기록을 쓰고, 성공 시 `_webSessions`와 pending joinRequests를 생성하며 일회용 코드 잔여 횟수를 차감한다. 웹 토큰 만료는 발급 시점 +8시간이고 초대 코드 만료와 독립적이다. `unknown-code`는 조회 결과가 정확히 1건이 아닐 때이므로 0건과 중복 2건을 구분하지 않는다. [web/functions/api.mjs:75](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:75>), [web/functions/protocol.mjs:27](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/protocol.mjs:27>).

## 스트림·수명·권한

- `entries`는 `projects/{projectId}/sessions/{sessionId}/scriptEntries` 전체 collection listener. limit/pagination 없이 각 스냅샷 전체 문서를 createdAt 내림차순 정렬한다. `data:[]`를 수신해야 빈 컬렉션이라고 판단할 수 있다. 초기값 `[]`, 연결 끊김, 타임아웃은 빈 결과의 증거가 아니다. [web/functions/api.mjs:195](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:195>).
- 전체 컬렉션 스냅샷은 DB에 저장된 기록 전체라는 뜻이다. BLE 누락/오프라인/저장 실패로 DB에 없는 촬영까지 보증하지 않는다. camera/script/entries는 별도 리스너라 서로 동일 시점의 원자적 스냅샷도 아니다.
- 10초 heartbeat, 최대 45초 또는 토큰 잔여시간까지 연결. 재접속 때 토큰 재검증. 토큰 문서 삭제 시 연결 종료. 프론트는 20초 watchdog와 재연결을 사용한다. [web/functions/api.mjs:173](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:173>), [web/src/session.js:38](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/src/session.js:38>).
- 신규 join은 종료 세션을 410으로 거부한다. 이미 받은 미만료 토큰은 access 문서가 남아 있으면 GET events가 종료 상태를 검사하지 않아 읽기 가능하다. 세션 문서가 없어도 access가 있으면 camera:null과 남은 하위 컬렉션을 받을 수 있다.
- 만료된 토큰은 401; 갱신 API 없음. 초대 코드가 만료돼도 기존 토큰은 자체 만료까지 유효하다. cleanup은 웹 세션/속도 제한 기록만 정리한다.
- **읽기와 수정 권한은 다르다.** events에는 `assertWebPermission`이 없다. pending/rejected/revoked admission도 유효 토큰이 있으면 데이터 읽기가 차단되지 않는다. command/script는 Host 승인 검사. 이를 새 읽기 API의 승인 정책으로 자동 계승하지 말고 명시적으로 설계해야 한다. [web/functions/api.mjs:154](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/api.mjs:154>), [web/functions/protocol.mjs:60](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/protocol.mjs:60>).

## 영구 촬영 기록과 필드 의미

`upsertTakeRecord`는 session scriptEntries와 project takeRecords를 동일 batch로 merge 저장한다. `listenProjectTakeRecords`는 프로젝트 전체를 createdAt 순서로 구독하며 projectKey는 검증/진단에만 쓰이고 서버 필터에는 쓰이지 않는다. 문서에 sessionId가 있으므로 새 조회에서 `where('sessionId','==',...)`가 가능하나 현재 메서드/API는 그 필터를 제공하지 않는다. 정렬을 결합한다면 배포 인덱스를 확인해야 한다. [blackmagician/blackmagician/SessionService.swift:936](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/SessionService.swift:936>), [blackmagician/blackmagician/SessionService.swift:1011](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/SessionService.swift:1011>).

`endSession`은 종료 플래그를 저장하고 삭제하지 않는다. 조사한 앱/웹 운영 소스에서는 takeRecords 만료 정리·세션 종료 시 삭제·프로젝트 기록 삭제 경로를 찾지 못했다. 영구 보존 보장은 아니다: 관리자 삭제, 외부 작업, DB TTL 정책은 별도 확인 필요. 호환 Rules가 배포되어 있다면 takeRecords의 write 허용에 delete도 포함된다. [blackmagician/blackmagician/SessionViewModel.swift:1521](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/SessionViewModel.swift:1521>), [web/firestore.compat.rules:15](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/firestore.compat.rules:15>).

| 필드 | 의미·제약 |
|---|---|
| takeId/id, sessionId | 세션·recordCounter 기반 식별과 세션 소속. 미디어 내장 고유 ID는 아님 |
| clipName | slateForName 정규화 또는 reel_C### 합성; 실제 파일명과 일치 보장 안 됨 |
| clipToken | reel + `|` + 계산된 clipNumber. 카메라/세션 없이 전역 고유하지 않음 |
| scene | 카메라 상태의 씬 문자열; 이후 기록 편집 가능 |
| cutNumber | 앱 scriptState 컷 번호 |
| scriptTake | 씬/컷 연속성 및 scriptState를 반영한 스크립트 테이크 |
| cameraTake / take | 카메라 take 값; legacy take는 cameraTake와 동일하게 저장 |
| cameraId / cameraName | 저장됨. cameraId는 A 등 논리 식별자이며 하드웨어 serial/UUID 보장 없음 |
| reel | 저장됨. 실제 카드 매체 UUID/카드 교체 이력/슬롯별 고유 ID는 기록 모델에 없음 |
| FPS / 코덱 / 해상도 | take 레코드 필드에 없음. 세션 현재 상태의 fps/brawSetting/resolution과 구분 |
| recordStartTC / recordStopTC | 저장되지만 현재 녹화 경로에서 시작 00:00:00:00, 끝은 로컬 경과시간과 fps로 계산 |
| createdAt | 레코드 생성 시 앱 Date; 정확한 녹화 시작 시각/서버 확정 시각으로 간주 불가 |

필드 생성 [blackmagician/blackmagician/ScriptLogEntry.swift:250](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/ScriptLogEntry.swift:250>), [blackmagician/blackmagician/ScriptLogEntry.swift:280](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/ScriptLogEntry.swift:280>); 직렬화 [blackmagician/blackmagician/ScriptLogEntry.swift:531](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/ScriptLogEntry.swift:531>). Host가 REC 종료를 감지하면 해당 시점 cameraState에서 일부 필드를 복사한다. 이는 녹화 시작 시 고정된 전체 촬영 설정 스냅샷이 아니다. scene/notes 등은 후속 수정 가능하다. [blackmagician/blackmagician/SessionViewModel.swift:1184](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/SessionViewModel.swift:1184>), [blackmagician/blackmagician/SessionViewModel.swift:2715](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/SessionViewModel.swift:2715>). 현재 상태 필드는 [blackmagician/blackmagician/CameraSessionState.swift:293](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/blackmagician/blackmagician/CameraSessionState.swift:293>).

검증 범위는 명시적으로 projectId + sessionId + shootDayKey + cameraId + reel + 이번 백업의 클립/카드 목록으로 좁혀야 한다. reel 재사용과 합성 이름 충돌은 ambiguous로 남긴다. planned 컷과 실제 기록도 분리하고, 나중에 촬영한 클립을 현재 카드의 누락으로 판정하지 않는다.

## Firebase 직접 조회와 배포 Rules

- `firebase.json`은 web/firestore.compat.rules를 선택한다. 루트 firestore.rules는 읽기를 true로 허용하지만 쓰기 조건은 별개다. compat는 `_webSessions`/`_webJoinLimits`를 차단하고 native 프로젝트 기록은 매우 넓게 read/write 허용한다. **이는 로컬 파일 내용이지 실제 배포 규칙 확인 완료가 아니다.** [firebase.json:3](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/firebase.json:3>), [web/firestore.compat.rules:9](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/firestore.compat.rules:9>), [firestore.rules:245](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/firestore.rules:245>).
- Firebase Console의 대상 프로젝트 Rules URL로 접근했으나 프로젝트 Rules 대신 시작 화면으로 이동했다. 실제 릴리스 Rules/배포 DB/IAM은 조회하지 못했다. Debug/Release 설정의 Firebase PROJECT_ID는 둘 다 black-magician-2bc98이다. Vercel 런타임 GCP_PROJECT_ID와의 일치는 별도 미확인.
- 조사한 앱 Swift에서 FirebaseAuth 로그인/ID-token 흐름을 찾지 못했다. deviceId·초대/프로젝트 비밀번호 흐름을 Firebase 사용자 인증으로 취급하면 안 된다. 현재 '기존 사용자 인증으로 접근 가능'이라고 확정할 근거가 없다.
- Firebase REST/SDK 직접 조회는 서버가 실제 배포 Rules로 허용해야 한다. API key는 권한이 아니다. 웹 opaque token도 직접 Firestore 인증에 사용할 수 없다. 넓은 Rules를 활용해 연동을 완성하는 방식을 권장하지 않는다.
- Vercel은 getVercelOidcToken → Google STS → 전용 서비스 계정 impersonation으로 Firestore 서버 자격을 얻는다. 이는 IAM 경로이며 클라이언트 Rules와 분리된다. 로컬 앱에서 Vercel OIDC를 그대로 사용할 수 없고 서비스 계정 개인키를 번들에 넣지 않는다. [web/functions/vercel.mjs:25](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/functions/vercel.mjs:25>).

## 실제 검증 결과와 한계

1. 2026-09-11 21:34 KST 무인증 GET /api/events: HTTP 401, application/json, `{"code":"unauthenticated","message":"초대 코드로 다시 접속해 주세요."}`. 인증된 읽기 또는 DB 성공 증거가 아니다.
2. 사용자가 이번 테스트로 재제공한 코드로 POST /api/join **1회**: HTTP 404 `unknown-code`. 토큰 미발급, events 미호출, 실제 entries 수신 예시 없음. 코드·토큰은 이 보고서에 보관하지 않는다. DB 조회 불일치 응답과 일관되지만 현재 로컬 코드와 배포 일치/프로젝트 연결까지 증명하지 않는다.
3. `node --test web/tests/*.test.mjs`: 10/10 PASS. invite 만료/소진, command/permission, gRPC Authorization 보존 등 단위 테스트. 실제 DB 통합 성공 증거가 아니다.
4. web/tests/integration.mjs는 에뮬레이터를 요구하며 이번에는 실행하지 않았다. 기존 stream 테스트는 camera 이벤트/변경을 확인하지만 전체 initial entries·종료 세션 읽기까지 검증하지 않는다. [web/tests/integration.mjs:126](</Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician/web/tests/integration.mjs:126>).
5. 앞선 Vercel 대시보드 확인은 Ready, /api/index, ICN1, Node24, 60초였으며 이번 현행 서버 소스와 구분한다. 배포된 함수 소스 전체/실제 Rules는 미확인.

## 방식 비교 및 권장

| 방식 | 장점 | 한계 | 판단 |
|---|---|---|---|
| 기존 NDJSON | 기존 서버 재사용, 세션 기록 전체 초기 수신 | 8시간, 종료 후 신규 join 불가, live-state 혼합, 한 세션 고정 | 단기 검증용 |
| Firebase 직접 조회 | takeRecords의 sessionId 필터 등 유연 | 실제 Rules·사용자 인증 미확인, DB 스키마 결합, 현재 허용 규칙 의존 위험 | 현 상태에서는 비권장 |
| 별도 읽기 API | 종료 세션, 최소 권한, 스냅샷 버전·범위·완전성 계약 가능 | 서버/인증/메타데이터 추가 구현 | 운영 권장 |

최소 조회 예제: [read_session.py](./read_session.py). 기존 승인 웹 세션 JSON을 mode 0600 로컬 파일로 전달한다. `python read_session.py /secure/path/test-web-session.json`. httpx 필요. join하지 않으며 반환된 eventsUrl만 사용, 같은 HTTPS origin 제한, redirect 차단, 전체 25초 제한, 실제 entries 수신/빈 배열/실패 구분, 출력은 필드명과 개수만. 함수 반환은 메모리의 데이터로 후속 대조에 사용 가능. 이 예제는 구문 검증만 완료했고 인증 성공 실데이터로는 미검증이다. SSE로 서버 계약이 바뀌면 content-type을 보고 별도 파서를 구현해야 하며 묵시적으로 섞지 않는다.

Data Handler는 datamanager.done의 복제 성공과 datahelper.done 및 reports[].json_path 준비를 확인한 뒤 완료 이벤트 처리에 검증 단계를 연결한다. 현재 watcher가 datahelper 완료 후 최종 보고를 만드는 경로에 새 단계를 추가해야 한다. live 진행률 감시 불필요. credential은 request/state/events에 넣지 않는다. DataHelper 현 JSON은 클립명·FPS·codec·해상도·TC를 포함하지만 씬/컷·카메라·릴 필드는 없으므로 누락 메타데이터는 unknown 처리하거나 향후 별도 추출 계약을 승인받아야 한다.
