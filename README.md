# 쥬쥬핑 월드 (scrap)

주소 기준 반경 내 어린이 체육 학원(태권도, 검도, 유도 등) 검색

**웹사이트:** https://jujuping.netlify.app/

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
python scraper.py --max 100
python scraper.py --address "수원시 팔달구" --radius 20 --max 200
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
python scraper_kakao.py --max 100
```

카카오 REST API 키는 https://developers.kakao.com 에서 앱 등록 후 발급

## 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--address`, `-a` | 기준 주소 | 경기 안성시 공도읍 서동대로 4473-1 |
| `--radius`, `-r` | 검색 반경 (km) | 30 |
| `--max`, `-m` | 최대 결과 수 | 500 |
| `--keywords`, `-k` | 검색 키워드 | 태권도 검도 유도 등 13개 |
| `--output`, `-o` | 결과 저장 경로 | result/현재시간/ |

## 결과

`result/YYYYMMDD_HHMMSS/` 폴더에 저장:

| 파일 | 형식 |
|------|------|
| `academies.csv` | CSV |
| `academies.xlsx` | Excel |
| `academies.json` | JSON |

포함 정보: 학원명, 카테고리, 주소, 전화번호, 거리(km), 링크
