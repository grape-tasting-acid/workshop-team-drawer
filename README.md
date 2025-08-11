# 조 추첨기

## 요구사항 대응
- 8개 조, 8명의 조장(남 4, 여 4) 전제
- 조장 외 인원은 `ob`(남), `yb`(남), `girls`(여)
- 여리더 팀에는 남성 인원(OB/YB) 잔여 우선 분배, 남리더 팀에는 여성 인원(girls) 잔여 우선 분배
- Tkinter GUI로 시각적 추첨, 결과를 엑셀(`.xlsx`)로 저장

## 실행 방법
1) 의존성 설치
```bash
cd /Users/lee/Desktop/lbox/mle/workshop/team_drawer
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

2) 실행 (택1)
```bash
# 데스크탑 GUI (Tkinter) - macOS에서 _tkinter 설치가 필요할 수 있음
python app.py

# 웹 GUI (Streamlit) - 브라우저에서 실행 (권장)
streamlit run streamlit_app.py
```

## 데이터 입력 형식
프로그램 최초 실행 시 `data/` 폴더에 예시 템플릿 CSV가 자동 생성됩니다.
- `leaders.csv`: 헤더 `name, gender` (gender는 M/F)
- `ob.csv`, `yb.csv`, `girls.csv`: 헤더 `name`

CSV는 UTF-8 인코딩 권장.

## macOS에서 Tkinter 오류 대안
만약 `ModuleNotFoundError: No module named '_tkinter'` 오류가 발생하면 macOS 기본 파이썬 또는 Homebrew로 `python-tk`를 설치해야 합니다. 빠른 우회로는 웹 GUI 버전(Streamlit)을 사용하는 것입니다.

## 결과 내보내기
- GUI에서 "엑셀로 저장" 버튼을 누르면 `output/` 폴더에 `draw_result_YYYYMMDD_HHMMSS.xlsx`가 생성됩니다.
- `ByTeam` 시트: 팀별로 나열, `Flat` 시트: 모든 행을 평면 구조로 나열

## 시드 고정
- GUI 상단 `Seed` 입력 후 추첨하면 재현 가능한 결과가 생성됩니다.
