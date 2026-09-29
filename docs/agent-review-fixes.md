# 에이전트 재검토 수정

- 앱과 Telegram의 완료 판정을 `orchestrator/completion.py`로 통일했다. 복제 검증, 복제 위치 수에 맞는 검수 결과, 성공 종료 코드, 누락 artifact 없음 및 PDF 경로 선언을 확인한다. 현재 디스크 연결 여부는 과거 완료 사실과 분리한다.
- Telegram 후속 요청에 동일 principal의 앞선 완료 메시지와 응답 네 쌍을 전달한다. 다른 사용자나 이후 요청은 포함하지 않는다.
- 실행 시작 예외 발생 시 principal로 소유권을 확인한 계획의 run_id/status를 채팅 응답에 보존한다.
- health는 추론 서버를 최대 2초 동안 확인하며, Telegram 연결은 최근 90초의 통신 성공 기록으로 판단한다.
- 재현 회귀 테스트 6개를 추가했다. 전체 orchestrator 테스트: 197 passed, 1 skipped. 실제 사용자 미디어나 외부 Telegram 메시지를 이용한 신규 복제 작업은 실행하지 않았다.
