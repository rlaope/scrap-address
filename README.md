# 어린이 체육 학원 검색기

주소 기준 반경 내 어린이 체육 학원(태권도, 검도, 유도 등)을 카카오 로컬 API로 검색합니다.

## 준비

1. https://developers.kakao.com 에서 앱 등록 후 **REST API 키** 발급
2. 의존성 설치:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 사용법

```bash
# 기본값 (안성시 공도읍 / 30km)
python scraper.py

# 주소 변경
python scraper.py --address "서울시 강남구 역삼동"

# 반경 변경
python scraper.py --radius 15

# 주소 + 반경 변경
python scraper.py --address "수원시 팔달구" --radius 20

# 키워드 직접 지정
python scraper.py --keywords 태권도 검도 유도
```

처음 실행 시 API 키를 입력하면 `.env` 파일에 자동 저장됩니다.

## 결과 파일

`output/` 폴더에 3가지 형식으로 저장됩니다:

| 파일 | 형식 | 용도 |
|------|------|------|
| `academies.csv` | CSV (UTF-8) | 엑셀/구글시트에서 열기 |
| `academies.xlsx` | Excel | 바로 열기 |
| `academies.json` | JSON | 프로그램 연동 |

각 파일에 포함되는 정보: 학원명, 카테고리, 지번주소, 도로명주소, 전화번호, 위도, 경도, 거리(km), 검색키워드, 카카오링크