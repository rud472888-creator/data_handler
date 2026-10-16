# 영상 수치 QA v1

두 가지를 원본 파일 수정 없이 검사하는 독립 Python CLI입니다.

1. 시간축 밝은/어두운 국소 이상 픽셀 후보
2. 디코딩된 RGB의 채널별 하이라이트/섀도 임계값 점유율

Imajev 연동, 카메라 RAW 디코더, 센서 불량 확정 검사, 학습 모델은 아닙니다. FFmpeg가 실제 디코딩할 수 있는 일반 영상 파일이 대상입니다. 운영 저장소나 사용자 컴퓨터 설정을 변경하지 않습니다.

## 설치 및 실행

Python 3.10+, FFmpeg/ffprobe 5.1+, NumPy, Pillow가 필요합니다. FFmpeg와 ffprobe가 PATH에 있어야 합니다. 의존성은 requirements.txt에 있습니다.

```sh
cd qa/video_numeric  # 저장소 루트 기준
python -m pip install -r requirements.txt
python video_qa.py "input.mov" --out "qa_result"
python video_qa.py "input.mov" --out "pixel_result" --modules pixels --pixel-delta 0.25 --min-frames 8 --min-seconds 0.2
python video_qa.py "input.mov" --out "clip_result" --modules clipping --threshold-preset endpoints --shadow-threshold 0.01 --highlight-threshold 0.99
python -m unittest discover -v
```

출력 폴더는 새 경로여야 합니다. 기존 폴더를 덮어쓰지 않습니다. 입력 파일은 읽기만 하며 subprocess는 shell 없이 인수 배열로 호출합니다. 종료 코드 0은 해당 실행의 처리가 완료됐다는 뜻이지, 영상 품질 합격 판정이 아닙니다. 실패/부분 실패는 2입니다. 처리 중 문제가 나면 가능한 경우 report.json에 partial_failure와 실제 처리 프레임 수를 남깁니다. 프로브 자체 실패나 경로 검증 실패는 출력 폴더 생성 전 종료할 수 있습니다.

## 1. 이상 픽셀 후보의 정확한 의미

원래 해상도의 모든 디코딩 프레임에 대해, 각 RGB 채널에서 중심 픽셀과 주변 8픽셀 중앙값의 차이를 구합니다. 밝은 후보는 어느 한 채널의 양의 차이, 어두운 후보는 어느 한 채널의 음의 차이 크기가 pixel-delta 이상인 경우입니다. 차이는 0..65535 디코딩 RGB 범위 대비 비율입니다. 바깥 한 픽셀 테두리는 검사에서 제외됩니다.

같은 좌표가 연속 min-frames 프레임 이상이면서 min-seconds 초 이상 유지된 구간만 pixel_intervals.csv에 기록합니다. 두 조건을 모두 만족해야 합니다. 기본값 0.25 / 8프레임 / 0.2초는 미보정 시작값으로, 제조사 규격이나 합격 기준이 아닙니다. 실제 프레임 시간 간격을 이용하며 중간 후보 공백을 합치지 않습니다. 단순 평균 이미지 검사가 아닙니다.

검출은 데드/핫/스턱 픽셀의 **후보**를 찾습니다. 픽셀 값이 문자 그대로 고정됐는지, 센서에서 발생했는지는 확정하지 않습니다. 정지 장면의 작은 불빛, 별, 반사점, 텍스트 모서리도 동일하게 검출될 수 있습니다. 합성 테스트에도 이 모호함을 확인하는 테스트가 있습니다. 흔들림 보정 전 영상과 움직이는 장면, 별도 다크/플랫 촬영을 활용한 후속 검증을 권합니다. 압축, 디베이어, 리사이즈로 결함이 여러 픽셀에 퍼지면 놓칠 수 있습니다.

## 2. 클리핑 수치의 정확한 의미와 색 범위

FFmpeg로 첫 번째 비디오 스트림을 RGB48LE, full-range 출력으로 변환하여 계산합니다. RGB 값 / 65535에 대해 shadow는 <=, highlight는 >= 비교입니다. R/G/B 각각과 ANY(채널 합집합)의 픽셀 수, 면적 비율, 외접 사각형을 저장합니다. ANY는 RGB 비율의 합이 아닙니다. bbox는 흩어진 모든 해당 픽셀을 감싸며 하나의 연결 영역을 뜻하지 않습니다.

- --threshold-preset endpoints: shadow 0, highlight 1. 정확한 디코딩 RGB 끝점 점유율입니다.
- --threshold-preset near-endpoints: shadow 0.01, highlight 0.99. 근흑색/근백색 점유율 프리셋입니다. 끝점 클리핑과 구분해서 해석하세요.
- 원본 full/legal(limited) range 태그는 보고서에 기록합니다. 어느 프리셋도 원본 YUV legal-range 준수 여부를 검사하지 않습니다.
- --shadow-threshold, --highlight-threshold를 주면 각각의 프리셋 값을 덮어씁니다.
- 원본 10비트 YUV의 64/940 같은 코드값을 RGB48 결과에 그대로 적용하지 않습니다.
- YUV→RGB 변환, 매트릭스, 반올림 때문에 원본 legal white가 RGB65535에 도달하지 않을 수 있습니다. 따라서 기본 highlight=1은 밝은 영역을 과소 집계할 수 있습니다. 필요하면 0.99처럼 근백색 임계값을 명시하되, 이는 끝점 클리핑과 다른 지표입니다.
- 원본 YUV 코드의 클리핑이나 센서 포화를 검증하려면 별도 원본 색 공간 분석/카메라 정보가 필요합니다. 이 도구는 **센서 클리핑을 확정하지 않습니다**.
- 감마/전달함수를 선형화하지 않으며 HDR 톤매핑도 하지 않습니다. PQ/HLG에서는 장면 휘도나 디스플레이 포화 의미로 해석하면 안 됩니다.

원본 pix_fmt/bit depth/색 primaries/transfer/matrix/range 등 ffprobe 메타데이터와 실제 변환 설명을 report.json에 기록합니다. 태그가 없거나 불명확하면 경고합니다. FFmpeg 기본 추정이 쓰일 수 있으므로 색 파이프라인이 확인되지 않은 결과는 참고용입니다. RGB48 출력은 16비트 **컨테이너**를 의미하며 8비트 소스에 정보를 추가하지 않습니다.

## 결과 파일

- report.json: 완료/부분실패 상태, 오류, 경고, 소스 메타데이터, 임계값, 프레임 수, 후보 수, 채널별 평균/최대 점유율, 증거 이미지 목록
- pixel_intervals.csv: bright/dark, 원본 x/y 좌표, 시작 프레임, 연속 프레임 수, 시작/종료 PTS, 지속 초
- clipping_frames.csv: 매 프레임/채널의 shadow/highlight 개수, 면적 비율, 외접 사각형
- clipping_intervals.csv: 채널별 clip-min-pixels 이상이 연속 발생한 시간 구간과 최대 면적 비율
- bright/dark_persistence.png: 모든 국소 잔차 후보의 프레임 점유 비율 히트맵. 지속 조건으로 필터된 확정 결함 지도가 아닙니다.
- shadow/highlight_occupancy.png: ANY 채널 임계값 점유 비율 히트맵
- *.npy: 픽셀별 수치 맵. *_candidate_frame_fraction은 전체 분석 프레임 대비 잔차 후보 비율, *_longest_run_seconds는 지속 기준 미달을 포함한 최장 연속 초, shadow/highlight_frame_fraction은 ANY 점유 비율
- evidence/*.png: 최대 max-crops개 8비트 미리보기 원본 크롭. 활성 종류(bright, dark, shadow, highlight)에 한도를 균등 예약하므로 먼저 나온 종류가 나중 종류의 몫을 소진하지 않습니다. 나머지는 위 순서로 배분하며 사용하지 않은 몫은 재분배하지 않습니다. 한도가 종류 수보다 작으면 일부 종류의 몫이 0일 수 있습니다. report.json의 evidence_quotas에 실제 배분을 기록합니다. x/y 및 crop_xyxy는 report.json에서 확인. 후보/클리핑을 처음 관찰한 일부 예시이며 심각도 순위가 아닙니다.

좌표 원점은 좌상단, 프레임 번호는 0부터, 구간은 [시작, 종료)입니다. CSV 시간은 소스 PTS이므로 반드시 0에서 시작하지 않습니다. 회전 태그는 자동 적용하지 않습니다. VFR은 ffprobe의 실제 프레임 PTS를 사용하고 마지막 프레임은 packet duration 또는 명시된 nominal FPS로 종료를 추정합니다. PTS가 누락/역행하면 nominal FPS를 쓸 수 있으나 횟수와 경고를 기록합니다. 쓸 FPS도 없으면 실패합니다. VFR의 맵 비율과 평균 면적은 **프레임 가중치**이며 시간 가중치가 아닙니다.

## 범위와 자원

전체 프레임을 저장하지 않습니다. 디코더 프레임 2개, 고정 크기 누적 맵과 작업 배열을 유지하며, 주변 중앙값은 128행 블록과 정확한 8입력 정렬 네트워크로 처리합니다. 기존 np.median과 같은 두 가운데 값의 평균을 쓰며 uint16 덧셈 오버플로를 피합니다. 메모리는 영상 길이가 아니라 해상도에 비례하지만 고해상도에서는 상당할 수 있습니다. CSV 파일 크기는 길이/검출 횟수에 비례합니다. ffmpeg 디코딩과 ffprobe 타임스탬프 추출이 각각 스트림을 읽으므로 실시간 처리 속도를 보장하지 않습니다. 긴 영상은 먼저 대표 구간으로 성능을 확인하세요.

중간 해상도 변경은 지원하지 않고 부분 실패 처리합니다. 첫 비디오 스트림만 검사합니다. 디코딩 오류나 선언된 프레임 수 불일치를 정상 완료로 처리하지 않습니다. 단, 컨테이너가 오류 없이 짧게 끝나고 원래 프레임 수가 알려져 있지 않다면 누락을 항상 알아낼 수는 없습니다. 손상 영상의 모든 형태를 검출한다는 보장은 없습니다. 강제 종료/디스크 부족 시 최종 보고서 생성이 보장되지 않습니다.

## 합성 데모와 검증

sample_source.mkv는 32×24 / 10fps / 12프레임의 무손실 RGB16 합성 영상입니다. 밝은 픽셀 (7,6), 어두운 픽셀 (13,12), 2프레임 일시점 (9,8), 고정 밝은 사각형, R만 포화된 점 (17,16)이 있습니다. 생성 결과는 저장소에 포함하지 않습니다. 아래 명령으로 sample_output을 새로 생성할 수 있습니다.

```sh
python video_qa.py sample_source.mkv --out sample_output --min-frames 5 --min-seconds 0.4
```

내장 unittest는 지속/일시 후보, 정지 물체 오탐 모호함, 채널 차이/면적, 지속 시간, 증거 이미지, 입력 불변, 덮어쓰기 거부와 없는 입력 실패를 검증합니다. 별도의 독립 검증 결과는 VALIDATION.md에 기록합니다. 실제 촬영물에 대한 정확도/재현율을 검증한 버전은 아닙니다.


## 리뷰 수정판 검증 및 통합 범위

저장소 루트에서도 다음으로 QA 회귀 테스트를 실행할 수 있습니다.

```sh
python -m unittest discover -s qa/video_numeric -v
python -m unittest qa.video_numeric.test_video_qa qa.video_numeric.test_regressions -v
python -m pytest qa/video_numeric orchestrator/tests
python -m qa.video_numeric.benchmark_residual --width 1920 --height 1080 --repeats 5
```

orchestrator만 지정하는 기존 테스트 명령은 이 독립 QA 테스트를 포함하지 않습니다. 위 결합 명령을 명시적으로 실행하세요. 런 상태/events/UI 및 별도 visual_qa 모듈과의 통합은 이 PR 범위에 포함되지 않습니다. 모든 프레임 분석, 기본 임계값과 채널 OR 판정은 유지합니다. 약한 결함이나 압축으로 퍼진 결함의 실촬영 재현율은 아직 미검증이며 임계값 최적화 결과로 해석하지 마세요.

FFmpeg/ffprobe는 `-v error`로 실행하므로 일반 경고는 오류 로그에 포함되지 않습니다. 출력된 오류 로그와 비정상 종료는 보수적으로 실패 처리합니다. 프레임 중복/드롭 방지에는 `-fps_mode passthrough`를 사용합니다.
