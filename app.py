"""
어린이 체육 학원 검색기 - 웹 인터페이스
Flask 기반, Render 배포용
"""

import io
import threading
import time
import uuid
from dataclasses import asdict

import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file

from scraper_kakao import (
    KakaoLocalClient,
    load_api_key,
    search_academies,
    fetch_detail_address,
    Academy,
    SEARCH_KEYWORDS,
    DEFAULT_ADDRESS,
    DEFAULT_RADIUS_KM,
)

app = Flask(__name__)

# In-memory task storage
tasks: dict = {}


@app.route("/")
def index():
    return render_template(
        "index.html",
        keywords=SEARCH_KEYWORDS,
        default_address=DEFAULT_ADDRESS,
        default_radius=int(DEFAULT_RADIUS_KM),
    )


@app.route("/api/search", methods=["POST"])
def start_search():
    data = request.get_json()
    task_id = str(uuid.uuid4())

    tasks[task_id] = {
        "status": "running",
        "progress": "시작 중...",
        "count": 0,
        "result": None,
    }

    thread = threading.Thread(target=_run_search, args=(task_id, data))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(
        {
            "status": task["status"],
            "progress": task["progress"],
            "count": task.get("count", 0),
        }
    )


@app.route("/api/download/<task_id>")
def download(task_id):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "Not ready"}), 404

    output = task["result"]
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="체육학원_검색결과.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _run_search(task_id: str, data: dict) -> None:
    try:
        address = data.get("address", DEFAULT_ADDRESS)
        radius = float(data.get("radius", DEFAULT_RADIUS_KM))
        max_results = int(data.get("max_results", 500))
        keywords = data.get("keywords", list(SEARCH_KEYWORDS))

        if not keywords:
            keywords = list(SEARCH_KEYWORDS)

        tasks[task_id]["progress"] = "좌표 변환 중..."

        api_key = load_api_key()
        client = KakaoLocalClient(api_key)
        center_lat, center_lng = client.geocode(address)

        tasks[task_id]["progress"] = "학원 검색 중..."
        academies = search_academies(
            client, center_lat, center_lng, radius, keywords
        )

        if max_results > 0:
            academies = sorted(academies, key=lambda a: a.distance_km)[:max_results]

        total = len(academies)
        tasks[task_id]["count"] = total
        tasks[task_id]["progress"] = f"상세 정보 조회 중... (0/{total})"

        # Enrich with detail address + zip code
        enriched: list[Academy] = []
        for i, ac in enumerate(academies):
            tasks[task_id]["progress"] = f"상세 정보 조회 중... ({i + 1}/{total})"

            place_id = (
                ac.place_url.rstrip("/").split("/")[-1] if ac.place_url else ""
            )
            zip_code = client.lookup_zipcode(ac.road_address)

            detail = ""
            if place_id:
                full_addr = fetch_detail_address(place_id)
                if full_addr and ac.road_address:
                    base = ac.road_address.strip()
                    if full_addr.startswith(base):
                        detail = full_addr[len(base) :].strip()
                    elif base in full_addr:
                        idx = full_addr.index(base)
                        detail = full_addr[idx + len(base) :].strip()
                    else:
                        detail = full_addr
                time.sleep(0.1)

            enriched.append(
                Academy(
                    name=ac.name,
                    category=ac.category,
                    address=ac.address,
                    road_address=ac.road_address,
                    detail_address=detail if detail else "동호수 정보 없음",
                    phone=ac.phone,
                    zip_code=zip_code,
                    latitude=ac.latitude,
                    longitude=ac.longitude,
                    distance_km=ac.distance_km,
                    search_keyword=ac.search_keyword,
                    place_url=ac.place_url,
                )
            )

        # Create Excel
        tasks[task_id]["progress"] = "엑셀 파일 생성 중..."
        sorted_academies = sorted(enriched, key=lambda a: a.distance_km)
        df = pd.DataFrame([asdict(a) for a in sorted_academies])
        df = df[
            [
                "name",
                "category",
                "address",
                "road_address",
                "detail_address",
                "phone",
                "zip_code",
                "place_url",
                "search_keyword",
            ]
        ]
        df.columns = [
            "학원명",
            "카테고리",
            "지번주소",
            "도로명주소",
            "상세주소",
            "전화번호",
            "우편번호",
            "링크",
            "검색키워드",
        ]

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="체육학원목록")
        output.seek(0)

        tasks[task_id]["result"] = output
        tasks[task_id]["status"] = "done"
        tasks[task_id]["progress"] = f"완료! {len(sorted_academies)}개 검색됨"
        tasks[task_id]["count"] = len(sorted_academies)

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["progress"] = f"오류: {str(e)}"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
