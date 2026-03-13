# EPM Tracker (Elevated Plus Maze)

**GitHub:** https://github.com/gdrpaul3-byte/hsmu_epm-tracker-v1

마우스 Elevated Plus Maze(EPM) 영상에서 자동으로 이동 경로를 추적하고, Open/Closed Arm 체류 시간을 분석하는 Python/OpenCV 도구입니다.

## 폴더 구조

```
epm/
├── src/
│   ├── epm_tracker.py              ← 메인 EPM 트래커
│   ├── epm_track_plotter.py        ← 트래킹 경로 시각화
│   └── analyze_epm_open_closed.py  ← Open/Closed Arm 분석
├── archive/                        ← 이전 버전 (참고용)
│   ├── epm_tracker_v1.py
│   └── epm_tracker_v2_notUse.py
├── data/
│   ├── videos/                     ← 원본 영상 (.mp4, gitignore 처리)
│   ├── tracks/                     ← 트래킹 결과 CSV
│   ├── configs/                    ← ROI/Zone JSON
│   ├── plots/                      ← 분석 그래프 (.png)
│   └── student_submissions/        ← 학생 제출 파일 (.zip)
├── assets/
│   └── NanumGothic*.ttf
└── docs/
```

## 환경 설정

```bash
conda activate opencv_312
# 또는
pip install -r requirements.txt
```

## 실행 방법

### 1. 트래커 실행
```bash
cd epm
python src/epm_tracker.py --video data/videos/m1_epm.mp4
```

### 2. Open/Closed Arm 분석
```bash
python src/analyze_epm_open_closed.py
```

### 3. 트래킹 경로 플롯
```bash
python src/epm_track_plotter.py
```

## 대용량 파일 안내

`data/videos/` 폴더의 mp4 파일은 `.gitignore`로 GitHub 업로드에서 제외됩니다.

## 의존성

```
opencv-python
numpy
Pillow
pandas
matplotlib
```
