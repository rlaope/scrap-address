"""
어린이 체육 학원(검도, 태권도 등) 검색 스크래퍼

사용법:
1. https://developers.kakao.com 에서 앱 등록 후 REST API 키 발급
2. .env 파일에 KAKAO_API_KEY=발급받은키 입력 또는 직접 실행 시 입력
3. python scraper.py [옵션]

예시:
  python scraper.py                                          # 기본값 사용
  python scraper.py --address "서울시 강남구 역삼동"          # 주소 변경
  python scraper.py --radius 15                              # 반경 15km
  python scraper.py --address "수원시 팔달구" --radius 20    # 주소+반경 변경
"""

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
import pandas as pd

# ── 기본 설정 ─────────────────────────────────────────────

DEFAULT_ADDRESS = "경기 안성시 공도읍 서동대로 4473-1"
DEFAULT_RADIUS_KM = 30
OUTPUT_DIR = Path(__file__).parent / "output"

# 검색 키워드 (어린이 체육 관련 학원)
SEARCH_KEYWORDS = [
    "태권도",
    "검도",
    "유도",
    "합기도",
    "무술",
    "체육관",
    "어린이체육",
    "키즈스포츠",
    "축구교실",
    "수영",
    "체조",
    "발레",
    "방과후체육",
]

KAKAO_API_BASE = "https://dapi.kakao.com/v2/local"


# ── 데이터 모델 ─────────────────────────────────────────

@dataclass(frozen=True)
class Academy:
    name: str
    category: str
    address: str
    road_address: str
    phone: str
    latitude: float
    longitude: float
    distance_km: float
    search_keyword: str
    kakao_place_url: str = ""


# ── 유틸리티 ─────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 거리를 km로 반환 (Haversine 공식)."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_api_key() -> str:
    """API 키를 환경변수 또는 .env 파일에서 로드."""
    key = os.environ.get("KAKAO_API_KEY")
    if key:
        return key

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("KAKAO_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    print("=" * 60)
    print("카카오 REST API 키가 필요합니다.")
    print("https://developers.kakao.com 에서 발급받을 수 있습니다.")
    print("=" * 60)
    key = input("API 키를 입력하세요: ").strip()
    if not key:
        print("API 키가 입력되지 않았습니다. 종료합니다.")
        sys.exit(1)

    # 다음 실행을 위해 .env 에 저장
    env_path.write_text(f"KAKAO_API_KEY={key}\n")
    print(f".env 파일에 저장되었습니다: {env_path}")
    return key


# ── 카카오 API 클라이언트 ──────────────────────────────────

class KakaoLocalClient:
    def __init__(self, api_key: str):
        self._headers = {"Authorization": f"KakaoAK {api_key}"}
        self._session = requests.Session()
        self._session.headers.update(self._headers)

    def geocode(self, address: str) -> tuple[float, float]:
        """주소를 위경도 좌표로 변환."""
        resp = self._session.get(
            f"{KAKAO_API_BASE}/search/address.json",
            params={"query": address},
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("documents"):
            raise ValueError(f"주소를 찾을 수 없습니다: {address}")

        doc = data["documents"][0]
        lat = float(doc["y"])
        lng = float(doc["x"])
        print(f"기준 좌표: {lat}, {lng} ({doc.get('address_name', address)})")
        return lat, lng

    def search_keyword(
        self,
        keyword: str,
        lat: float,
        lng: float,
        radius_m: int = 20000,
        page: int = 1,
    ) -> dict:
        """키워드로 장소 검색 (최대 반경 20km, 페이지당 15건)."""
        resp = self._session.get(
            f"{KAKAO_API_BASE}/search/keyword.json",
            params={
                "query": keyword,
                "y": lat,
                "x": lng,
                "radius": radius_m,
                "sort": "distance",
                "page": page,
                "size": 15,
            },
        )
        resp.raise_for_status()
        return resp.json()


# ── 메인 스크래핑 로직 ─────────────────────────────────────

def search_academies(
    client: KakaoLocalClient,
    center_lat: float,
    center_lng: float,
    radius_km: float,
    keywords: list[str],
) -> list[Academy]:
    """
    30km 반경 검색을 위해 카카오 API의 20km 제한을 우회:
    - 중심점 + 주변 6개 포인트에서 각각 20km 반경으로 검색
    - 결과를 합치고 중복 제거 후 30km 필터링
    """
    # 카카오 API 최대 반경 20km → 여러 중심점으로 커버
    search_points = _generate_search_points(center_lat, center_lng, radius_km)
    max_api_radius = 20000  # 20km in meters

    seen_ids: set[str] = set()
    results: list[Academy] = []

    total_searches = len(keywords) * len(search_points)
    current = 0

    for keyword in keywords:
        for point_lat, point_lng, label in search_points:
            current += 1
            print(
                f"\r  [{current}/{total_searches}] "
                f"'{keyword}' 검색 중 ({label})...",
                end="",
                flush=True,
            )

            page = 1
            while page <= 45:  # 카카오 API 최대 45페이지
                try:
                    data = client.search_keyword(
                        keyword, point_lat, point_lng, max_api_radius, page
                    )
                except requests.HTTPError as e:
                    print(f"\n  API 오류: {e}")
                    break

                documents = data.get("documents", [])
                if not documents:
                    break

                for doc in documents:
                    place_id = doc["id"]
                    if place_id in seen_ids:
                        continue
                    seen_ids.add(place_id)

                    p_lat = float(doc["y"])
                    p_lng = float(doc["x"])
                    dist = haversine(center_lat, center_lng, p_lat, p_lng)

                    if dist > radius_km:
                        continue

                    # 체육/스포츠/무술 관련 카테고리 필터
                    category = doc.get("category_name", "")
                    if not _is_sports_academy(category, doc.get("place_name", ""), keyword):
                        continue

                    academy = Academy(
                        name=doc.get("place_name", ""),
                        category=category,
                        address=doc.get("address_name", ""),
                        road_address=doc.get("road_address_name", ""),
                        phone=doc.get("phone", ""),
                        latitude=p_lat,
                        longitude=p_lng,
                        distance_km=round(dist, 2),
                        search_keyword=keyword,
                        kakao_place_url=doc.get("place_url", ""),
                    )
                    results.append(academy)

                meta = data.get("meta", {})
                if meta.get("is_end", True):
                    break
                page += 1

                time.sleep(0.1)  # API 속도 제한 방지

            time.sleep(0.15)

    print()  # 줄바꿈
    return results


def _generate_search_points(
    center_lat: float, center_lng: float, radius_km: float
) -> list[tuple[float, float, str]]:
    """
    중심 + 주변 6개 포인트 생성 (30km를 20km 반경으로 커버).
    """
    points = [(center_lat, center_lng, "중심")]
    offset_km = 15  # 겹치는 영역을 확보하기 위해 15km 간격

    for i, direction in enumerate(["북", "북동", "남동", "남", "남서", "북서"]):
        angle = math.radians(i * 60)
        d_lat = (offset_km / 111.0) * math.cos(angle)
        d_lng = (offset_km / (111.0 * math.cos(math.radians(center_lat)))) * math.sin(angle)
        points.append((center_lat + d_lat, center_lng + d_lng, direction))

    return points


def _is_sports_academy(category: str, name: str, keyword: str) -> bool:
    """체육/스포츠/무술 관련 학원인지 판별."""
    sports_terms = {
        "태권도", "검도", "유도", "합기도", "무술", "무도",
        "체육", "체조", "스포츠", "수영", "축구", "농구",
        "발레", "댄스", "체력", "운동", "키즈", "어린이",
        "피트니스", "격투", "권투", "복싱", "배드민턴",
        "탁구", "클라이밍", "볼링", "인라인", "스케이트",
        "짐", "도장", "관",
    }

    text = f"{category} {name}".lower()

    # 카테고리에 '체육' 또는 '스포츠' 포함
    if any(t in category for t in ["체육", "스포츠", "무도", "무술"]):
        return True

    # 이름이나 카테고리에 스포츠 관련 용어 포함
    if any(term in text for term in sports_terms):
        return True

    # 검색 키워드와 직접 매칭
    if keyword in text:
        return True

    return False


# ── 결과 저장 ─────────────────────────────────────────────

def save_results(
    academies: list[Academy],
    output_dir: Path,
    address: str = DEFAULT_ADDRESS,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> None:
    """결과를 CSV와 Excel로 저장."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not academies:
        print("검색 결과가 없습니다.")
        return

    # 거리순 정렬
    sorted_academies = sorted(academies, key=lambda a: a.distance_km)

    # DataFrame 생성
    df = pd.DataFrame([asdict(a) for a in sorted_academies])
    df.columns = [
        "학원명", "카테고리", "지번주소", "도로명주소", "전화번호",
        "위도", "경도", "거리(km)", "검색키워드", "카카오링크",
    ]

    # CSV 저장
    csv_path = output_dir / "academies.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"CSV 저장: {csv_path}")

    # Excel 저장
    xlsx_path = output_dir / "academies.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="체육학원목록")

        # 열 너비 자동 조정
        ws = writer.sheets["체육학원목록"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(
                df[col].astype(str).str.len().max(),
                len(col),
            )
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = (
                min(max_len + 2, 50)
            )

    print(f"Excel 저장: {xlsx_path}")

    # JSON 저장
    json_path = output_dir / "academies.json"
    json_path.write_text(
        json.dumps(
            [asdict(a) for a in sorted_academies],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"JSON 저장: {json_path}")

    # 요약 출력
    print(f"\n{'=' * 60}")
    print(f"총 {len(sorted_academies)}개 체육 학원 검색 완료")
    print(f"기준: {address}")
    print(f"반경: {radius_km}km")
    print(f"{'=' * 60}")

    # 키워드별 통계
    keyword_counts = df["검색키워드"].value_counts()
    print("\n[키워드별 검색 결과]")
    for kw, count in keyword_counts.items():
        print(f"  {kw}: {count}건")

    # 거리별 분포
    print("\n[거리별 분포]")
    bins = [0, 5, 10, 15, 20, 25, 30]
    for i in range(len(bins) - 1):
        count = len(df[(df["거리(km)"] >= bins[i]) & (df["거리(km)"] < bins[i + 1])])
        if count > 0:
            print(f"  {bins[i]}~{bins[i+1]}km: {count}건")


# ── 실행 ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="어린이 체육 학원 검색기 (카카오 로컬 API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python scraper.py                                          # 기본값 사용
  python scraper.py --address "서울시 강남구 역삼동"          # 주소 변경
  python scraper.py --radius 15                              # 반경 15km
  python scraper.py --address "수원시 팔달구" --radius 20    # 주소+반경 변경
  python scraper.py --keywords 태권도 검도 유도              # 키워드 지정
        """,
    )
    parser.add_argument(
        "--address", "-a",
        default=DEFAULT_ADDRESS,
        help=f"기준 주소 (기본값: {DEFAULT_ADDRESS})",
    )
    parser.add_argument(
        "--radius", "-r",
        type=float,
        default=DEFAULT_RADIUS_KM,
        help=f"검색 반경 km (기본값: {DEFAULT_RADIUS_KM})",
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        default=None,
        help="검색 키워드 목록 (기본값: 태권도 검도 유도 등 13개)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=f"결과 저장 디렉토리 (기본값: {OUTPUT_DIR})",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    address = args.address
    radius_km = args.radius
    keywords = args.keywords or SEARCH_KEYWORDS
    output_dir = Path(args.output) if args.output else OUTPUT_DIR

    print("=" * 60)
    print("어린이 체육 학원 검색기")
    print(f"기준 주소: {address}")
    print(f"검색 반경: {radius_km}km")
    print(f"검색 키워드: {', '.join(keywords)}")
    print("=" * 60)

    api_key = load_api_key()
    client = KakaoLocalClient(api_key)

    # 1. 주소 → 좌표 변환
    print("\n[1/3] 주소 좌표 변환 중...")
    try:
        center_lat, center_lng = client.geocode(address)
    except (ValueError, requests.HTTPError) as e:
        print(f"오류: {e}")
        sys.exit(1)

    # 2. 학원 검색
    print("\n[2/3] 체육 학원 검색 중...")
    academies = search_academies(
        client, center_lat, center_lng, radius_km, keywords
    )

    # 3. 결과 저장
    print("\n[3/3] 결과 저장 중...")
    save_results(academies, output_dir, address, radius_km)


if __name__ == "__main__":
    main()