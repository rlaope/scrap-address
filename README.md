# 어린이 체육 학원 검색기

주소 기준 반경 내 어린이 체육 학원(태권도, 검도, 유도 등) 검색

## 설치

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 버전 1: API 키 없이 사용

```bash
python scraper.py
python scraper.py --address "서울시 강남구 역삼동"
python scraper.py --radius 15
python scraper.py --address "수원시 팔달구" --radius 20
python scraper.py --keywords 태권도 검도 유도
```

## 버전 2: 카카오 API 키 사용 (정확도 높음)

1. `.env` 파일 생성:
```
KAKAO_API_KEY=여기에_REST_API_키_입력
```

2. 실행:
```bash
python scraper_kakao.py
python scraper_kakao.py --address "서울시 강남구 역삼동" --radius 20
```

카카오 REST API 키는 https://developers.kakao.com 에서 앱 등록 후 발급

## 결과

`output/` 폴더에 저장:

| 파일 | 형식 |
|------|------|
| `academies.csv` | CSV |
| `academies.xlsx` | Excel |
| `academies.json` | JSON |

포함 정보: 학원명, 카테고리, 주소, 전화번호, 거리(km), 링크
