# -*- coding: utf-8 -*-
"""
남해 뚜벅이버스 추천 백엔드 (Flask)
-------------------------------------------------------------
엔드포인트
  GET  /                  : 테스트용 페이지(templates/index.html)
  POST /api/recommend     : {"text": "..."} -> place1~place4 (정류장 순서)
  GET  /api/nearby        : ?lat=&lng=&radius=2000 -> 반경 내 음식점/카페
  GET  /api/schedule      : 버스 시간표(JSON 원본)

실행:
  python app.py          (개발 서버, http://127.0.0.1:5000)
"""
import os

# 임베딩 모델은 로컬 캐시에서만 로드(네트워크 조회로 인한 행 방지).
# 캐시에 없으면 recommend.py 가 자동으로 키워드 폴백으로 동작한다.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import requests
from flask import Flask, jsonify, render_template, request

try:
    # python-dotenv 가 있으면 .env 자동 로드
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from recommend import StationRecommender

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "namhae_stations.json")

app = Flask(__name__)

# 서버 시작 시 1회 로드 + 임베딩 사전 계산
recommender = StationRecommender(DATA_PATH)

KAKAO_REST_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
# 지도 표시(JS SDK)용 — REST 키와 다른 'JavaScript 키'
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", "").strip()
KAKAO_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"


# ---------------------------------------------------------------------------
# 카카오 로컬 — 카테고리(반경) 검색
#   FD6 = 음식점, CE7 = 카페
# ---------------------------------------------------------------------------
def kakao_nearby(lat, lng, radius=2000, group_codes=("FD6", "CE7"), max_pages=3):
    if not KAKAO_REST_KEY:
        raise RuntimeError("KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다.")

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    items = []
    for code in group_codes:
        page = 1
        while page <= max_pages:
            params = {
                "category_group_code": code,
                "x": lng,                       # 경도
                "y": lat,                       # 위도
                "radius": min(int(radius), 20000),  # 카카오 최대 20000m
                "sort": "distance",
                "page": page,
                "size": 15,
            }
            resp = requests.get(KAKAO_CATEGORY_URL, headers=headers, params=params, timeout=6)
            resp.raise_for_status()
            payload = resp.json()
            for d in payload.get("documents", []):
                items.append({
                    "name": d.get("place_name"),
                    "category_code": code,
                    "category": "카페" if code == "CE7" else "음식점",
                    "category_detail": d.get("category_name"),
                    "address": d.get("road_address_name") or d.get("address_name"),
                    "phone": d.get("phone") or None,
                    "lat": float(d["y"]),
                    "lng": float(d["x"]),
                    "distance_m": int(d["distance"]) if d.get("distance") else None,
                    "url": d.get("place_url"),
                })
            if payload.get("meta", {}).get("is_end", True):
                break
            page += 1

    items.sort(key=lambda x: (x["distance_m"] is None, x["distance_m"] or 0))
    return items


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", kakao_js_key=KAKAO_JS_KEY)


@app.route("/favicon.ico")
def favicon():
    # 브라우저 자동 요청 — 404 노이즈 제거용(콘텐츠 없음)
    return ("", 204)


@app.post("/api/recommend")
def api_recommend():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "요청 본문에 text 가 필요합니다."}), 400

    result = recommender.recommend(text, top_n=4)
    meta = recommender.data.get("metadata", {})
    result["city"] = recommender.data.get("city") or meta.get("city")
    result["transport"] = recommender.data.get("transport") or meta.get("transport")
    return jsonify(result)


@app.get("/api/nearby")
def api_nearby():
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", default=2000, type=int)
    if lat is None or lng is None:
        return jsonify({"error": "lat, lng 쿼리 파라미터가 필요합니다."}), 400

    try:
        items = kakao_nearby(lat, lng, radius)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except requests.RequestException as e:
        return jsonify({"error": f"카카오 API 요청 실패: {e}"}), 502

    return jsonify({
        "center": {"lat": lat, "lng": lng},
        "radius": radius,
        "count": len(items),
        "items": items,
    })


@app.get("/api/schedule")
def api_schedule():
    # 옛 데이터: 최상위 bus_schedule / 새 데이터: 정류장별 schedule
    bus = recommender.data.get("bus_schedule")
    if bus:
        return jsonify(bus)
    return jsonify({
        "stops": [
            {
                "stop_id": st.get("stop_id"),
                "stop_name": recommender._stop_name(st),
                "schedule": st.get("schedule", {}),
            }
            for st in recommender.data.get("stations", [])
        ]
    })


@app.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "engine": "embedding" if recommender.use_embedding else "keyword",
        "kakao_key_loaded": bool(KAKAO_REST_KEY),
        "place_count": len(recommender.items),
    })


if __name__ == "__main__":
    # 포트는 PORT 환경변수로 변경 가능 (macOS는 5000을 AirPlay가 점유할 수 있음)
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
