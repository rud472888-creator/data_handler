# 로컬 LLM 실동작 검증

- 설치 모델: Qwen3.8-27B MLX 8bit. 서버는 127.0.0.1에만 바인딩하고 HF_HUB_OFFLINE=1 및 TRANSFORMERS_OFFLINE=1로 실행한다.
- `script/verify_local_agent.py`는 실제 설치된 모델을 호출한다. 첫 요청, 원본 경로 추가, 복제 위치 추가의 세 차례 한국어 대화로 계획을 생성했다. 프로젝트 ID, 원본, 두 복제 위치를 코드에서 대조한 뒤 테스트 fixture 계획만 승인했다.
- 실제 DataManager/DataHelper 프로세스를 실행해 두 복제본 SHA-256 일치 및 PDF 3개를 확인했다. 최종 phase는 reported다.
- 증거: `.pipeline/local-llm-nxrrua9x/transcript.json`, `result.json`, `runs/run-agent-929f51d9207b/events/`.
- 추론 요청은 루프백 서버만 이용했다. 이 검증에서 실제 Telegram 메시지를 발송하거나 사용자 촬영 미디어를 복제하지 않았다.
- 전체 회귀 검사: 198 passed, 1 skipped. 모델 호출 검증은 위 별도 스크립트로 수행한다.
- 앱 진입 시 사전 로딩, 15초 상태 갱신, 30분 미사용 후 메모리 해제, 재실행 시 대화 선택 보존을 구성했다.
- 첫 로딩 속도와 장시간 운영 안정성은 메모리 사용 및 미디어 크기에 따라 달라진다. 검증 결과는 모든 입력과 장애 상황에 대한 무오류 보장이 아니다.
- 이번 실제 모델 3회 요청 소요 시간: 20.17초, 4.21초, 16.99초. 로컬 부하에 따라 달라진다.
- 최종 패키지의 native WebView에서 한국어 상태 요청에 대한 응답을 확인했다. Cmd+Q 종료 후 재실행 시 에이전트 모드, 선택한 대화, 사용자 요청과 모델 응답이 복원됐다.
- 최종 앱 codesign 검증 통과. 두 launchd 서비스의 RunAtLoad/KeepAlive와 오프라인 모델 환경변수를 확인했다.
