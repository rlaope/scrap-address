"""
어린이 체육 학원 검색기 - 카카오 API 키 버전 (정확도 높음)

사용법:
  1. .env 파일에 KAKAO_API_KEY=발급받은키 입력
  2. python scraper_kakao.py
"""

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import requests
import pandas as pd

DEFAULT_ADDRESS = "경기 안성시 공도읍 서동대로 4473-1"
DEFAULT_RADIUS_KM = 30
OUTPUT_DIR = Path(__file__).parent / "result"

SEARCH_KEYWORDS = [
    "태권도", "검도", "유도", "합기도", "무술", "체육관",
    "어린이체육", "키즈스포츠", "축구교실", "수영", "체조", "발레", "방과후체육",
]

KAKAO_API_BASE = "https://dapi.kakao.com/v2/local"


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


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_api_key():
    key = os.environ.get("KAKAO_API_KEY")
    if key:
        return key
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("KAKAO_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("KAKAO_API_KEY가 없습니다. .env 파일에 설정해주세요.")
    sys.exit(1)


class KakaoLocalClient:
    def __init__(self, api_key):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"KakaoAK {api_key}"})

    def geocode(self, address):
        resp = self._session.get(f"{KAKAO_API_BASE}/search/address.json", params={"query": address})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("documents"):
            raise ValueError(f"주소를 찾을 수 없습니다: {address}")
        doc = data["documents"][0]
        lat, lng = float(doc["y"]), float(doc["x"])
        print(f"기준 좌표: {lat}, {lng}")
        return lat, lng

    def search_keyword(self, keyword, lat, lng, radius_m=20000, page=1):
        resp = self._session.get(
            f"{KAKAO_API_BASE}/search/keyword.json",
            params={"query": keyword, "y": lat, "x": lng, "radius": radius_m, "sort": "distance", "page": page, "size": 15},
        )
        resp.raise_for_status()
        return resp.json()


def search_academies(client, center_lat, center_lng, radius_km, keywords):
    search_points = _generate_search_points(center_lat, center_lng, radius_km)
    seen_ids = set()
    results = []
    total = len(keywords) * len(search_points)
    current = 0

    for keyword in keywords:
        for point_lat, point_lng, label in search_points:
            current += 1
            print(f"\r  [{current}/{total}] '{keyword}' 검색 중 ({label})...", end="", flush=True)
            page = 1
            while page <= 45:
                try:
                    data = client.search_keyword(keyword, point_lat, point_lng, 20000, page)
                except requests.HTTPError:
                    break
                documents = data.get("documents", [])
                if not documents:
                    break
                for doc in documents:
                    if doc["id"] in seen_ids:
                        continue
                    seen_ids.add(doc["id"])
                    p_lat, p_lng = float(doc["y"]), float(doc["x"])
                    dist = haversine(center_lat, center_lng, p_lat, p_lng)
                    if dist > radius_km:
                        continue
                    category = doc.get("category_name", "")
                    if not _is_sports_academy(category, doc.get("place_name", ""), keyword):
                        continue
                    results.append(Academy(
                        name=doc.get("place_name", ""), category=category,
                        address=doc.get("address_name", ""), road_address=doc.get("road_address_name", ""),
                        phone=doc.get("phone", ""), latitude=p_lat, longitude=p_lng,
                        distance_km=round(dist, 2), search_keyword=keyword,
                        place_url=doc.get("place_url", ""),
                    ))
                if data.get("meta", {}).get("is_end", True):
                    break
                page += 1
                time.sleep(0.1)
            time.sleep(0.15)
    print()
    return results


def _generate_search_points(center_lat, center_lng, radius_km):
    points = [(center_lat, center_lng, "중심")]
    offset_km = 15
    for i, d in enumerate(["북", "북동", "남동", "남", "남서", "북서"]):
        angle = math.radians(i * 60)
        d_lat = (offset_km / 111.0) * math.cos(angle)
        d_lng = (offset_km / (111.0 * math.cos(math.radians(center_lat)))) * math.sin(angle)
        points.append((center_lat + d_lat, center_lng + d_lng, d))
    return points


def _is_sports_academy(category, name, keyword):
    sports_terms = {"태권도","검도","유도","합기도","무술","무도","체육","체조","스포츠","수영","축구","농구","발레","댄스","체력","운동","키즈","어린이","피트니스","격투","권투","복싱","배드민턴","탁구","클라이밍","볼링","인라인","스케이트","짐","도장","관"}
    text = f"{category} {name}"
    if any(t in category for t in ["체육","스포츠","무도","무술"]):
        return True
    if any(term in text for term in sports_terms):
        return True
    if keyword in text:
        return True
    return False


def save_results(academies, output_dir, address, radius_km):
    output_dir.mkdir(parents=True, exist_ok=True)
    if not academies:
        print("검색 결과가 없습니다.")
        return
    sorted_academies = sorted(academies, key=lambda a: a.distance_km)
    df = pd.DataFrame([asdict(a) for a in sorted_academies])
    df.columns = ["학원명","카테고리","지번주소","도로명주소","전화번호","위도","경도","거리(km)","검색키워드","링크"]

    csv_path = output_dir / "academies.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"CSV 저장: {csv_path}")

    xlsx_path = output_dir / "academies.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="체육학원목록")
    print(f"Excel 저장: {xlsx_path}")

    json_path = output_dir / "academies.json"
    json_path.write_text(json.dumps([asdict(a) for a in sorted_academies], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 저장: {json_path}")

    print(f"\n총 {len(sorted_academies)}개 검색 완료 (기준: {address}, 반경: {radius_km}km)")


def main():
    parser = argparse.ArgumentParser(description="어린이 체육 학원 검색기 (카카오 API 키 버전)")
    parser.add_argument("--address", "-a", default=DEFAULT_ADDRESS)
    parser.add_argument("--radius", "-r", type=float, default=DEFAULT_RADIUS_KM)
    parser.add_argument("--keywords", "-k", nargs="+", default=None)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--max", "-m", type=int, default=0, help="최대 결과 수 (0=무제한)")
    args = parser.parse_args()

    address = args.address
    radius_km = args.radius
    keywords = args.keywords or SEARCH_KEYWORDS
    max_results = args.max
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else OUTPUT_DIR / timestamp

    print(f"기준: {address} / 반경: {radius_km}km" + (f" / 최대: {max_results}개" if max_results else ""))

    api_key = load_api_key()
    client = KakaoLocalClient(api_key)

    print("[1/3] 좌표 변환...")
    center_lat, center_lng = client.geocode(address)

    print("[2/3] 학원 검색...")
    academies = search_academies(client, center_lat, center_lng, radius_km, keywords)

    if max_results > 0:
        academies = sorted(academies, key=lambda a: a.distance_km)[:max_results]

    print("[3/3] 저장...")
    save_results(academies, output_dir, address, radius_km)


if __name__ == "__main__":
    main()