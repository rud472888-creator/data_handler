# 연동 구현용 프롬프트

두 프롬프트는 별도 프로젝트 세션에서 순서대로 사용한다. 먼저 Blackmagician 계약을 확정하고 그 결과를 Data Handler 작업에 전달한다. 현재 조사 결과는 같은 폴더 report.md 참고. 아래 API는 신규 제안이지 기존 API가 아니다.

## 1. Blackmagician 개발 세션에 전달

Blackmagician에 Data Handler용 촬영 기록 읽기 API를 구현해줘.

실제 저장소: /Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician
Data Handler 조사 보고서: /Users/ijaegyeong/Documents/data_handler/docs/blackmagician-integration/report.md
배포: https://blackmagician-web.vercel.app
AGENTS.md의 오래된 Desktop 경로 대신 실제 Documents 경로와 Git 루트를 확인해. 다른 세션의 변경을 보존하고 관련 파일만 수정해.

목표는 백업이 끝난 로컬 Data Handler가 특정 프로젝트·촬영 세션의 확정 기록을 받아 클립 누락과 메타데이터를 검증하는 것이야. 기존 카메라 제어 권한은 필요 없어.

현재 소스를 다시 확인할 것:
- web/functions/api.mjs, vercel.mjs, protocol.mjs, web/src/session.js, web/vercel.json
- firebase.json, firestore.rules, web/firestore.compat.rules와 실제 배포 Rules
- SessionService.swift의 takeRecords 이중 쓰기와 ScriptLogEntry.swift, SessionViewModel.swift의 녹화 종료 기록 생성
현재 /api/events는 SSE가 아닌 NDJSON이고 opaque 웹 토큰은 8시간이야. 종료 세션 신규 join은 거부되며 GET에는 admission 검사가 없어. 제안했던 manifest API는 아직 없어. 클립별 FPS/codec/resolution이 없고 TC는 로컬 elapsed 표시값이므로 실제 TC로 내보내지 마.

구현 요구:
1. 프로젝트·세션에 범위가 제한된 읽기 전용 인증 계약을 설계하고 구현해. 만료·철회·프로젝트 소유/허용 여부를 서버에서 검증하고 종료 세션도 권한 내에서 조회 가능하게 해. 기존 control 초대 코드를 무인 반복 소비하는 방식은 쓰지 마. 인증 선택에 필요한 기존 계정 체계를 먼저 조사하고, 사용자 계정이 없으면 있다고 가정하지 마. 인증/권한의 실제 운영 부여는 배포 검토 항목으로 남겨.
2. 제안 경로 GET /api/projects/{projectId}/sessions/{sessionId}/manifest를 구현하되 경로를 변경하면 이유와 최종 계약을 문서화해. projects/{projectId}/takeRecords를 sessionId로 한정하고, 종료/삭제/권한없음/빈기록을 구분해. projectKey와 projectId를 혼동하지 마.
3. schemaVersion, projectId, sessionId, sessionEnded, generatedAt, sourceRevision 또는 일관된 스냅샷 식별, totalCount, complete, 필터 범위를 반환해. 큰 기록은 스냅샷 일관성을 유지하는 페이지/커서로 수신 완전성을 검증할 수 있게 해. 단순 페이지별 시각 조회를 원자적 스냅샷이라고 표기하지 마.
4. takeId, cameraId, reel, clipName/clipToken 및 provenance, scene/cut/scriptTake/cameraTake, shootDay, source, 기록 상태를 제공해. 비밀값·Host deviceId·초대코드를 allowlist 밖에 둬.
5. 녹화 시작/종료 당시 확인한 FPS(유리수와 off-speed 구분), codec/BRAW setting, width/height, 카메라 식별, 실제 카드 식별 가능 여부, metadataObservedAt/source를 클립별로 보존해. 미지원 값은 null/unknown. 기존 과거 기록을 현재 설정으로 채우지 마. 실제 TC가 없으면 null과 timecodeSource=unavailable/local_elapsed 등으로 명시하고 elapsedDuration을 따로 보존해. 합성 clipName은 실제 파일명으로 단정하지 마.
6. 기존 scriptEntries/takeRecords 이중 쓰기 및 편집 호환성을 유지하고 보존·삭제 정책을 문서화해. 인증 없는 read/write가 허용된 실제 Rules인지 확인하되 무작정 열거나 다른 앱을 깨는 변경을 하지 마. Rules 강화는 기존 클라이언트 인증 마이그레이션과 함께 검토 가능한 변경으로 준비해.
7. 테스트: 다른 프로젝트 접근 거부, 미승인/만료/철회 인증, 종료 세션 허용 범위, 빈 결과와 오류, 전체 페이지 완전성, 촬영중 변경, 합성 이름 충돌, metadata unknown, 과거 기록 호환. 테스트 데이터는 emulator 또는 명시적 테스트 세션만 사용하고 비밀값을 출력하지 마.
8. API 계약, 읽기 전용 클라이언트 예제, 테스트 결과, 추가 인덱스/환경 설정 및 배포 변경 목록을 제출해. 실제 권한 확대·배포는 구체적인 diff와 검증 결과를 준비한 뒤 기존 세션의 승인 범위에 따라 처리해.

iOS 검증 기준: DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer, project=blackmagician/blackmagician.xcodeproj, scheme=blackmagician, destination='platform=iOS Simulator,name=iPhone 17'. 웹/API만 수정한다면 관련 테스트를 우선 실행하고 iOS 변경 시 앱 검사도 수행해.

## 2. Data Handler 개발 세션에 전달

Data Handler에 Blackmagician 촬영 기록 대조 단계를 구현해줘.

작업 저장소: /Users/ijaegyeong/Documents/data_handler
조사 보고서: /Users/ijaegyeong/Documents/data_handler/docs/blackmagician-integration/report.md
조회 예제: /Users/ijaegyeong/Documents/data_handler/docs/blackmagician-integration/read_session.py
Blackmagician 소스는 /Users/ijaegyeong/Documents/잡다다/프로젝트/blackmagician에 있지만 다른 세션에서 개발하므로 읽기만 해. DataManager/DataHelper도 수정하지 말고 orchestrator에 구현해.

먼저 Blackmagician 개발 세션이 확정한 최신 API 계약을 확인해. 이 프롬프트의 manifest 경로는 제안이므로 배포/구현 확인 없이 존재한다고 가정하지 마. 아직 읽기 API가 없다면 인터페이스/fixture 기반 구현까지만 진행하고 실제 연동 완료로 보고하지 마. 임시 NDJSON 방식은 유효한 승인 테스트 인증과 현재 활성 세션 범위에 한해 사용하고 자동 join은 금지해.

요구:
1. run 요청에 Blackmagician projectId/sessionId와 검증 범위(cameraId, reel, shootDay, 대상 카드·클립 목록)를 영구 기록해. 토큰은 OS Keychain 등 보안 저장소에서 참조하고 request/state/events/log에 넣지 마. 프로젝트 이름만으로 연결하지 마.
2. datamanager.done의 성공·replicas_complete 및 datahelper.done과 reports[].json_path 준비를 확인한 뒤 조회/대조해. 라이브 진행률 감시 대신 기존 완료 아티팩트 처리에 연결해. 로컬 에이전트 경로와 기존 Hermes/direct 경로 모두 누락 없이 연결해.
3. API의 전체 snapshot/page를 검증하고 스냅샷 ID·조회시각·범위·source hash를 안전한 로컬 artifact에 남겨. timeout/401/403/404/빈 entries/부분 페이지를 별도 상태로 구분해. 조회 실패 때문에 백업 성공을 실패로 덮어쓰지 말고 검증 상태를 분리해.
4. 비교는 결정적인 코드로 수행해. exact clip identity를 우선하고 카메라+릴+클립 및 실제 지원하는 메타데이터로 보완해. 합성명, 중복명, TC 출처 미확인, 범위 불명확은 ambiguous/unknown으로 남겨. 두 replica의 같은 클립을 촬영 중복으로 세지 마.
5. 결과 상태 matched/missing/unexpected/mismatch/ambiguous/unknown을 정의해. planned와 recorded, 스크립트 테이크와 카메라 테이크, 프레임레이트 유리수와 off-speed, elapsed와 실제 TC를 구분해. 없는 필드는 통과로 처리하지 마. 현재 DataHelper JSON에 없는 카메라·릴·씬 등은 추측하지 말고 추가 추출이 필요하다고 보고해.
6. 검증 결과와 completion artifact를 원자적으로 기록하고 재실행/중복 이벤트를 안전하게 처리해. 한 번 받은 범위의 최종 결과를 후속 촬영 기록으로 조용히 바꾸지 말고 재검증 버전을 남겨. 기존 최종 보고서에 결과와 근거 경로를 포함해.
7. 인증·네트워크 실패, 빈/부분 스냅샷, 중복 및 멀티카메라, 새 촬영 범위 제외, 메타데이터 미지원, 두 replica, 재실행과 이벤트 중복을 fixture로 테스트해. python -m pytest orchestrator/tests를 실행해.
8. 실미디어 run은 AGENTS.md에 따라 source/replica/project를 확인한 뒤 승인 범위에서 수행해. 보고서 전달은 기존 정책을 유지하고 새 외부 메시지 발송을 임의로 추가하지 마.

최종 제출: 변경 파일·API 계약 버전·테스트 근거·지원/미지원 범위·인증된 실제 샘플 검증 여부. 백업 파일에 접근하지 않았으면 누락 검증 성공이라고 보고하지 마.
