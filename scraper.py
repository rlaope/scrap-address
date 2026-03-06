"""
어린이 체육 학원(검도, 태권도 등) 검색 스크래퍼 (API 키 불필요)

사용법:
  python scraper.py                                          # 기본값 사용
  python scraper.py --address "서울시 강남구 역삼동"          # 주소 변경
  python scraper.py --radius 15                              # 반경 15km
  python scraper.py --address "수원시 팔달구" --radius 20    # 주소+반경 변경
"""

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import pandas as pd

# ── 기본 설정 ─────────────────────────────────────────────

DEFAULT_ADDRESS = "경기 안성시 공도읍 서동대로 4473-1"
DEFAULT_RADIUS_KM = 30
OUTPUT_DIR = Path(__file__).parent / "result"

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
    place_url: str = ""


# ── 유틸리티 ─────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# ── 카카오맵 웹 스크래퍼 (API 키 불필요) ─────────────────────

class KakaoMapScraper:
    """카카오맵 웹 검색 API를 사용 (API 키 불필요)."""

    SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
    GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"

    # 카카오맵 웹에서 사용하는 내부 검색 API
    WEB_SEARCH_URL = "https://search.map.kakao.com/mapsearch/map.daum.net/do/search"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://map.kakao.com/",
        })

    def geocode(self, address: str) -> tuple[float, float]:
        """주소를 위경도 좌표로 변환 (카카오맵 웹 검색 이용)."""
        resp = self._session.get(
            self.WEB_SEARCH_URL,
            params={
                "q": address,
                "HAM_ENCODING": "utf-8",
                "output": "json",
                "page": 1,
                "limit": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # 주소 검색 결과에서 좌표 추출
        addr_result = data.get("addr")
        if addr_result and addr_result.get("documents"):
            doc = addr_result["documents"][0]
            lat = float(doc.get("lat", doc.get("y", 0)))
            lng = float(doc.get("lng", doc.get("x", 0)))
            if lat and lng:
                print(f"기준 좌표: {lat}, {lng}")
                return lat, lng

        # place 결과에서 좌표 추출
        place_result = data.get("place")
        if place_result and place_result.get("documents"):
            doc = place_result["documents"][0]
            lat = float(doc.get("lat", doc.get("y", 0)))
            lng = float(doc.get("lng", doc.get("x", 0)))
            if lat and lng:
                print(f"기준 좌표: {lat}, {lng} ({doc.get('name', address)})")
                return lat, lng

        # 폴백: Nominatim (OpenStreetMap) 지오코딩
        return self._geocode_nominatim(address)

    def _geocode_nominatim(self, address: str) -> tuple[float, float]:
        """OpenStreetMap Nominatim 지오코딩 (폴백)."""
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "academy-scraper/1.0"},
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise ValueError(f"주소를 찾을 수 없습니다: {address}")

        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])
        print(f"기준 좌표: {lat}, {lng} (OSM)")
        return lat, lng

    def search_places(
        self,
        keyword: str,
        center_lat: float,
        center_lng: float,
        radius_km: float,
        page: int = 1,
    ) -> list[dict]:
        """카카오맵 웹 검색으로 장소 검색."""
        # 검색 영역 계산 (rect: left,top,right,bottom in longitude,latitude)
        d_lat = radius_km / 111.0
        d_lng = radius_km / (111.0 * math.cos(math.radians(center_lat)))

        rect = (
            f"{center_lng - d_lng},{center_lat + d_lat},"
            f"{center_lng + d_lng},{center_lat - d_lat}"
        )

        resp = self._session.get(
            self.WEB_SEARCH_URL,
            params={
                "q": keyword,
                "HAM_ENCODING": "utf-8",
                "output": "json",
                "rect": rect,
                "page": page,
                "limit": 15,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        place_data = data.get("place", {})
        return place_data.get("documents", [])


# ── 네이버 지역 검색 스크래퍼 (폴백) ────────────────────────

class NaverMapScraper:
    """네이버 지도 웹 검색 (API 키 불필요)."""

    SEARCH_URL = "https://map.naver.com/p/api/search/allSearch"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://map.naver.com/",
        })

    def geocode(self, address: str) -> tuple[float, float]:
        """네이버 지도로 주소 → 좌표 변환."""
        resp = self._session.get(
            "https://map.naver.com/p/api/search/allSearch",
            params={
                "query": address,
                "type": "address",
                "searchCoord": "",
                "boundary": "",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # 주소 결과
        addr_result = data.get("result", {}).get("address", {})
        items = addr_result.get("items", [])
        if items:
            point = items[0].get("point", {})
            lat = float(point.get("y", 0))
            lng = float(point.get("x", 0))
            if lat and lng:
                print(f"기준 좌표: {lat}, {lng} (네이버)")
                return lat, lng

        raise ValueError(f"주소를 찾을 수 없습니다: {address}")

    def search_places(
        self,
        keyword: str,
        center_lat: float,
        center_lng: float,
        page: int = 1,
    ) -> list[dict]:
        """네이버 지도 장소 검색."""
        resp = self._session.get(
            self.SEARCH_URL,
            params={
                "query": keyword,
                "type": "all",
                "searchCoord": f"{center_lng};{center_lat}",
                "page": page,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        place_result = data.get("result", {}).get("place", {})
        return place_result.get("list", [])


# ── 메인 스크래핑 로직 ─────────────────────────────────────

def search_academies(
    center_lat: float,
    center_lng: float,
    radius_km: float,
    keywords: list[str],
) -> list[Academy]:
    kakao = KakaoMapScraper()
    naver = NaverMapScraper()

    search_points = _generate_search_points(center_lat, center_lng, radius_km)
    seen: set[str] = set()  # name+address 기반 중복 제거
    results: list[Academy] = []

    total = len(keywords) * len(search_points)
    current = 0

    for keyword in keywords:
        for point_lat, point_lng, label in search_points:
            current += 1
            print(
                f"\r  [{current}/{total}] '{keyword}' 검색 중 ({label})...",
                end="", flush=True,
            )

            # 카카오맵 웹 검색
            for page in range(1, 6):  # 최대 5페이지
                try:
                    docs = kakao.search_places(
                        keyword, point_lat, point_lng, radius_km, page
                    )
                except Exception:
                    break

                if not docs:
                    break

                for doc in docs:
                    name = doc.get("name", doc.get("place_name", ""))
                    addr = doc.get("address", doc.get("address_name", ""))
                    dedup_key = f"{name}|{addr}"
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    p_lat = float(doc.get("lat", doc.get("y", 0)))
                    p_lng = float(doc.get("lng", doc.get("x", 0)))
                    if not p_lat or not p_lng:
                        continue

                    dist = haversine(center_lat, center_lng, p_lat, p_lng)
                    if dist > radius_km:
                        continue

                    category = doc.get("category", doc.get("category_name", ""))
                    if not _is_sports_academy(category, name, keyword):
                        continue

                    results.append(Academy(
                        name=name,
                        category=category,
                        address=addr,
                        road_address=doc.get("road_address", doc.get("road_address_name", "")),
                        phone=doc.get("phone", doc.get("tel", "")),
                        latitude=p_lat,
                        longitude=p_lng,
                        distance_km=round(dist, 2),
                        search_keyword=keyword,
                        place_url=doc.get("place_url", doc.get("link", "")),
                    ))

                time.sleep(0.2)

            # 네이버 지도 검색 (추가 결과)
            try:
                naver_docs = naver.search_places(keyword, point_lat, point_lng)
                for doc in naver_docs:
                    name = doc.get("name", "")
                    addr = doc.get("address", "")
                    dedup_key = f"{name}|{addr}"
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    p_lat = float(doc.get("y", 0))
                    p_lng = float(doc.get("x", 0))
                    if not p_lat or not p_lng:
                        continue

                    dist = haversine(center_lat, center_lng, p_lat, p_lng)
                    if dist > radius_km:
                        continue

                    category = doc.get("category", "")
                    if not _is_sports_academy(category, name, keyword):
                        continue

                    results.append(Academy(
                        name=name,
                        category=category,
                        address=addr,
                        road_address=doc.get("roadAddress", ""),
                        phone=doc.get("tel", ""),
                        latitude=p_lat,
                        longitude=p_lng,
                        distance_km=round(dist, 2),
                        search_keyword=keyword,
                        place_url=doc.get("thumUrl", ""),
                    ))
            except Exception:
                pass

            time.sleep(0.2)

    print()
    return results


def _generate_search_points(
    center_lat: float, center_lng: float, radius_km: float
) -> list[tuple[float, float, str]]:
    points = [(center_lat, center_lng, "중심")]
    offset_km = 15

    for i, direction in enumerate(["북", "북동", "남동", "남", "남서", "북서"]):
        angle = math.radians(i * 60)
        d_lat = (offset_km / 111.0) * math.cos(angle)
        d_lng = (offset_km / (111.0 * math.cos(math.radians(center_lat)))) * math.sin(angle)
        points.append((center_lat + d_lat, center_lng + d_lng, direction))

    return points


def _is_sports_academy(category: str, name: str, keyword: str) -> bool:
    sports_terms = {
        "태권도", "검도", "유도", "합기도", "무술", "무도",
        "체육", "체조", "스포츠", "수영", "축구", "농구",
        "발레", "댄스", "체력", "운동", "키즈", "어린이",
        "피트니스", "격투", "권투", "복싱", "배드민턴",
        "탁구", "클라이밍", "볼링", "인라인", "스케이트",
        "짐", "도장", "관",
    }

    text = f"{category} {name}"

    if any(t in category for t in ["체육", "스포츠", "무도", "무술"]):
        return True
    if any(term in text for term in sports_terms):
        return True
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
    output_dir.mkdir(parents=True, exist_ok=True)

    if not academies:
        print("검색 결과가 없습니다.")
        return

    sorted_academies = sorted(academies, key=lambda a: a.distance_km)

    df = pd.DataFrame([asdict(a) for a in sorted_academies])
    df.columns = [
        "학원명", "카테고리", "지번주소", "도로명주소", "전화번호",
        "위도", "경도", "거리(km)", "검색키워드", "링크",
    ]

    # CSV
    csv_path = output_dir / "academies.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"CSV 저장: {csv_path}")

    # Excel
    xlsx_path = output_dir / "academies.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="체육학원목록")
        ws = writer.sheets["체육학원목록"]
        for col_idx, col in enumerate(df.columns, 1):
            max_len = max(df[col].astype(str).str.len().max(), len(col))
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = min(max_len + 2, 50)
    print(f"Excel 저장: {xlsx_path}")

    # JSON
    json_path = output_dir / "academies.json"
    json_path.write_text(
        json.dumps([asdict(a) for a in sorted_academies], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"JSON 저장: {json_path}")

    # 요약
    print(f"\n{'=' * 60}")
    print(f"총 {len(sorted_academies)}개 체육 학원 검색 완료")
    print(f"기준: {address}")
    print(f"반경: {radius_km}km")
    print(f"{'=' * 60}")

    keyword_counts = df["검색키워드"].value_counts()
    print("\n[키워드별 검색 결과]")
    for kw, count in keyword_counts.items():
        print(f"  {kw}: {count}건")

    print("\n[거리별 분포]")
    bins = [0, 5, 10, 15, 20, 25, 30]
    for i in range(len(bins) - 1):
        count = len(df[(df["거리(km)"] >= bins[i]) & (df["거리(km)"] < bins[i + 1])])
        if count > 0:
            print(f"  {bins[i]}~{bins[i+1]}km: {count}건")


# ── 실행 ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="어린이 체육 학원 검색기 (API 키 불필요)",
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
    parser.add_argument("--address", "-a", default=DEFAULT_ADDRESS,
                        help=f"기준 주소 (기본값: {DEFAULT_ADDRESS})")
    parser.add_argument("--radius", "-r", type=float, default=DEFAULT_RADIUS_KM,
                        help=f"검색 반경 km (기본값: {DEFAULT_RADIUS_KM})")
    parser.add_argument("--keywords", "-k", nargs="+", default=None,
                        help="검색 키워드 목록 (기본값: 태권도 검도 유도 등 13개)")
    parser.add_argument("--output", "-o", default=None,
                        help=f"결과 저장 디렉토리 (기본값: {OUTPUT_DIR})")
    parser.add_argument("--max", "-m", type=int, default=500,
                        help="최대 결과 수 (기본값: 500)")
    return parser.parse_args()


def main():
    args = parse_args()

    address = args.address
    radius_km = args.radius
    keywords = args.keywords or SEARCH_KEYWORDS
    max_results = args.max
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else OUTPUT_DIR / timestamp

    print("=" * 60)
    print("어린이 체육 학원 검색기 (API 키 불필요)")
    print(f"기준 주소: {address}")
    print(f"검색 반경: {radius_km}km")
    print(f"검색 키워드: {', '.join(keywords)}")
    if max_results:
        print(f"최대 결과: {max_results}개")
    print("=" * 60)

    # 1. 주소 → 좌표 변환
    print("\n[1/3] 주소 좌표 변환 중...")
    scraper = KakaoMapScraper()
    try:
        center_lat, center_lng = scraper.geocode(address)
    except ValueError as e:
        print(f"오류: {e}")
        sys.exit(1)

    # 2. 학원 검색
    print("\n[2/3] 체육 학원 검색 중...")
    academies = search_academies(center_lat, center_lng, radius_km, keywords)

    if max_results > 0:
        academies = sorted(academies, key=lambda a: a.distance_km)[:max_results]

    # 3. 결과 저장
    print("\n[3/3] 결과 저장 중...")
    save_results(academies, output_dir, address, radius_km)


if __name__ == "__main__":
    main()
