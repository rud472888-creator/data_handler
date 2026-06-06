# Data Handler

Data Handler는 최상위 `orchestrator`가 복제 담당 `DataManager`와 검수 리포트 담당 `DataHelper`를 순서대로 묶어 실행하는 작업 폴더입니다. 이 저장소에서 `/goal`은 앱 내부 명령이 아닙니다. Codex 세션에서 긴 작업의 목표를 고정해 맡길 때 쓰는 지시 형식입니다.

## `/goal` 사용법

짧은 질문이나 단일 터미널 명령에는 `/goal`이 필요하지 않습니다. 여러 단계가 이어지고, 중간에 검증이나 커밋 같은 마무리 작업까지 필요할 때 사용합니다.

```text
/goal [완료 조건이 분명한 목표]
```

요청에는 아래 내용을 함께 적는 편이 좋습니다.

- 작업 대상: 수정할 파일, 기능, 문서 범위를 적습니다.
- 금지 범위: `DataManager`와 `DataHelper`처럼 건드리면 안 되는 영역을 적습니다.
- 완료 기준: 어떤 상태가 되면 끝났다고 볼지 적습니다.
- 검증 방법: 실행할 테스트나 확인 명령을 적습니다.
- 후속 처리: 커밋, 푸시, PR 생성 여부를 적습니다.

```text
/goal orchestrator/README.md에 승인 실행 절차를 보강해줘. DataManager와 DataHelper 소스는 수정하지 말고, 검증은 python -m pytest orchestrator/tests로 해줘. 완료하면 커밋하고 origin/main에 푸시해줘.
```

승인 실행을 맡길 때는 소스 경로, 복제 대상 경로, 프로젝트 이름을 먼저 확정해야 합니다. 값이 이미 적혀 있어도 실행 직전에는 다시 확인합니다.

```text
/goal 아래 값으로 승인 실행을 준비해줘. 실행 전에 값이 맞는지 다시 확인해줘.
SOURCE=/path/to/source
REPLICA_PATH_1=/path/to/replica-a
REPLICA_PATH_2=/path/to/replica-b
PROJECT_NAME=Project Name
```

확인 후 실행하는 명령은 아래 형식입니다.

```sh
python -m orchestrator.cli start \
  --source "$SOURCE" \
  --replica-path "$REPLICA_PATH_1" \
  --replica-path "$REPLICA_PATH_2" \
  --project-name "$PROJECT_NAME" \
  --profile macbook-dit-agent
```

완료 보고 전에는 다음을 확인합니다.

- 요청한 파일 변경이 실제로 반영됐는지 확인합니다.
- 지정된 검증 명령을 실행하고 결과를 남깁니다.
- 커밋이나 푸시를 요청받았다면 해당 작업까지 끝냅니다.
- 실행 작업이라면 `.pipeline/runs/<run_id>/request.json`, `state.json`, `events/*.done.json`를 기준으로 상태를 판단합니다.
- Hermes gateway 전달이 막히면 `delivery.<phase>.pending.json` 위치를 보고합니다.
