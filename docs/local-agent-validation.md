# 로컬 에이전트 설치 검증 — 2026-09-08

- Qwen3.8-27B MLX Q8의 고정 revision 다운로드 완료. MTP는 비활성화.
- `com.dit.data-handler.agent` / `com.dit.data-handler.inference` 사용자 launchd 서비스 설치 및 health 응답 확인.
- 실제 로컬 모델로 한국어 상태 요청, 명시적 복제 계획 추출, 정보 부족 요청, 삭제 지시 처리 확인. 명시적 계획에는 정확한 프로젝트 ID·원본·두 복제 경로가 반환됨.
- 로컬 모델의 초기 상태 요청 전체 지연 18.56초(로드 포함), 해당 생성 구간 5.61초. 수정한 계획 추출 프롬프트의 생성 구간 15.66초. 단일 표본이며 처리량 벤치마크가 아님.
- 테스트 영상으로 실제 agent plan 승인 → DataManager 복제 → 두 복제본 SHA-256 일치 → DataHelper PDF → offline outbox 보존 검증.
- 전체 orchestrator 테스트: 188 passed, 1 skipped. skip은 사용자 외장 원본을 지정해야 하는 live-media 테스트. 사용자 촬영 원본에 대한 작업은 실행하지 않음.
- 인증 없는 API 변경 차단, Telegram 발신자 allowlist, 일회용 pairing, 중복 승인, 원본 변경, symlink, 전송 실패 재시도 및 변조 첨부 차단 테스트 포함.
- Telegram 봇 `@DataHandlerDIT_Lee_0908_bot` 생성, getMe 토큰 검증 성공. 토큰·config 파일 권한 0600 확인.
- Telegram 일회용 `/start` 수신으로 사용자 계정 등록 완료. 연결 안내 응답의 전송 성공 확인(message_id=3).
- 설치된 outbox worker를 통해 연동 완료 안내(message_id=4)와 실제 테스트 영상 검수 PDF(message_id=5) 전송 성공 확인. 두 항목 모두 재시도 0회. 이는 Telegram API의 전송 성공 확인이며 사용자의 열람 여부를 의미하지 않음.
- 사용자 촬영 원본의 실제 원격 복제는 아직 실행하지 않음. 경로 확인 및 승인된 작업부터 수행 가능.

상세 테스트 결과는 작업 폴더 `.pipeline/agent-validation/tests.xml`, 모델 응답 근거는 같은 폴더의 `model-intents.json` 및 `explicit-plan.json`에 로컬 보관한다. 외부 서비스 토큰은 이 근거 파일에 포함하지 않는다.

Telegram 전달 완료 기록은 `.pipeline/agent-validation/telegram-delivery.json`에 보관한다.

사용 안내: [로컬 에이전트 README](../orchestrator/agent/README.md)
