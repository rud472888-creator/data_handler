# Data Handler 사용법

Data Handler는 촬영 원본을 여러 위치로 복제하고, 복제 결과와 클립 검수 리포트를 같은 실행 기록 안에 남기는 로컬 운영 도구입니다. 최상위 `orchestrator`가 `DataManager`로 복제를 시작하고, 완료 이벤트가 생기면 `DataHelper` 검수 단계를 한 번만 이어서 실행합니다.

## 기본 흐름

1. 소스 폴더, 복제 대상 폴더, 프로젝트 이름을 확정합니다.
2. Data Handler 앱이나 CLI에서 실행을 시작합니다.
3. 실행 기록은 `.pipeline/runs/<run_id>/` 아래에 쌓입니다.
4. `events/datamanager.done.json`이 생기면 DataHelper 단계가 이어집니다.
5. `events/datahelper.done.json`이 생기면 최종 리포트와 전달 상태를 확인합니다.

## 앱으로 실행

개발 환경에서는 앱 프런트를 먼저 띄웁니다.

```sh
python -m orchestrator.cli app --host 127.0.0.1 --port 8750
```

브라우저에서 `http://127.0.0.1:8750`을 열고 아래 순서로 진행합니다.

1. `New / Review`에서 프로젝트를 새로 만들거나 기존 프로젝트를 선택합니다.
2. 소스 경로와 복제 대상 경로를 확인합니다.
3. `Start Replication`에서 프로젝트, 소스, 목적지, 촬영일, 카메라 유닛을 확인합니다.
4. 실행이 시작되면 `Runs`와 진행 패널에서 상태와 산출물을 봅니다.

## CLI로 실행

터미널에서 직접 실행할 때도 소스 경로, 복제 대상 경로, 프로젝트 이름을 먼저 확정합니다.

```sh
python -m orchestrator.cli start \
  --source "$SOURCE" \
  --replica-path "$REPLICA_PATH_1" \
  --replica-path "$REPLICA_PATH_2" \
  --project-name "$PROJECT_NAME" \
  --profile macbook-dit-agent
```

소스가 여러 개이면 `--source`를 반복해서 넣습니다. 복제 대상이 더 있으면 `--replica-path`를 같은 방식으로 추가합니다. 명령이 정상적으로 시작되면 `run-...` 형식의 실행 ID가 출력됩니다.

## 완료 확인

실행 상태는 `.pipeline/runs/<run_id>/` 아래 파일을 기준으로 봅니다.

- `request.json`: 실행 요청 원본입니다.
- `state.json`: 현재 단계와 상태입니다.
- `events/datamanager.done.json`: DataManager 복제 단계 완료 이벤트입니다.
- `events/datahelper.started.json`: DataHelper 중복 실행을 막는 시작 기록입니다.
- `events/datahelper.done.json`: DataHelper 검수 단계 완료 이벤트입니다.
- `final-report.md`: 최종 리포트입니다.
- `delivery.<phase>.pending.json`: Hermes gateway 전달이 막혔을 때 남는 재시도 기록입니다.

Hermes 없이 로컬에서 완료 이벤트 처리를 확인하려면 아래 명령을 한 번 실행합니다.

```sh
python -m orchestrator.cli watch-once --direct
```

## macOS 앱 패키징

로컬 앱 번들과 DMG는 아래 명령으로 만듭니다.

```sh
./script/package_macos_app.sh
```

결과물은 `dist/Data Handler.app`과 `dist/Data Handler.dmg`입니다. 빌드 후 바로 실행할 때는 다음 명령을 씁니다.

```sh
./script/build_and_run.sh
```

패키징된 앱은 실행 상태를 `~/Library/Application Support/Data Handler/.pipeline`에 저장합니다. 배포용 서명과 공증은 별도 작업으로 남아 있습니다.

## 검증

수정한 영역에 맞는 테스트를 실행합니다.

```sh
python -m pytest orchestrator/tests
DataManager/.venv/bin/python -m pytest
DataHelper/.venv/bin/python -m pytest
```

오케스트레이터 문서나 앱 프런트만 바꿨다면 `python -m pytest orchestrator/tests`를 우선 확인합니다. `DataManager`와 `DataHelper` 소스는 명시적인 요청이 있을 때만 수정합니다.
