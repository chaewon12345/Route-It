# -*- coding: utf-8 -*-
"""
정류장/장소 추천 엔진
-------------------------------------------------------------
- 사용자 입력 텍스트(취향/여행스타일/동행)와 각 장소의 (이름+설명+키워드)를
  문장 임베딩으로 변환해 코사인 유사도를 측정한다.
- recommendable=false 정류장(홍현·경유지·터미널)은 후보에서 제외.
- 정류장마다 '대표 장소 1곳'(유사도 최고)을 뽑고, 정류장 단위로 상위 4개 선택.
- 결과는 버스 정류장 순서대로 정렬하고 place1~place4 키를 부여.

메인 경로: sentence-transformers(jhgan/ko-sroberta-multitask) 임베딩
폴백 경로: 모델 로드 실패 시 키워드 사전 기반 이진 코사인(인터넷/설치 불필요)
"""
import json
import math
import os

MODEL_NAME = "jhgan/ko-sroberta-multitask"

# ---------------------------------------------------------------------------
# 키워드 폴백용 사전 (임베딩 모델을 못 쓸 때만 사용)
#   사용자가 쓰는 일상어 -> 데이터의 키워드 태그로 매핑
# ---------------------------------------------------------------------------
TRIGGER = {
    "사진": ["사진", "찍", "인생샷", "포토", "스냅"],
    "포토": ["사진", "찍", "포토", "포토스팟"],
    "감성": ["감성", "분위기", "예쁜", "무드", "아기자기", "느좋"],
    "힐링": ["힐링", "쉬", "휴식", "여유", "편안", "쉼", "느긋"],
    "휴식": ["휴식", "쉬", "쉼", "여유"],
    "휴양": ["휴양", "휴식", "쉼"],
    "자연": ["자연", "숲", "바다", "산", "풍경", "들판"],
    "풍경": ["풍경", "경치", "뷰", "전망"],
    "경치": ["경치", "풍경", "뷰"],
    "전망": ["전망", "뷰", "풍경", "내려다"],
    "바다": ["바다", "해변", "해안", "바닷가", "오션", "해수욕"],
    "해변": ["해변", "바다", "바닷가", "해수욕"],
    "산": ["산", "등산", "트레킹"],
    "산책": ["산책", "걷", "걸어", "거닐"],
    "트레킹": ["트레킹", "등산", "하이킹", "걷기"],
    "레저": ["레저", "활동", "액티브", "활동적", "역동"],
    "스포츠": ["스포츠", "운동", "활동적"],
    "체험": ["체험", "만들", "해보", "활동적", "활동"],
    "갯벌체험": ["갯벌", "바지락"],
    "바지락": ["바지락", "갯벌"],
    "역사": ["역사", "옛", "전통", "유적"],
    "문화": ["문화", "전시", "예술", "갤러리"],
    "사찰": ["절", "사찰", "사원", "기도", "불교"],
    "절": ["절", "사찰"],
    "카페": ["카페", "커피", "디저트", "빵"],
    "식당": ["맛집", "식당", "먹", "음식", "로컬푸드"],
    "한식": ["한식", "백반", "한정식", "국밥"],
    "로컬": ["로컬", "현지", "지역", "토속"],
    "맥주": ["맥주", "술", "펍", "수제맥주"],
    "이국적": ["이국", "유럽", "독일", "외국"],
    "유럽": ["유럽", "독일", "이국"],
    "독일": ["독일"],
    "테마마을": ["테마", "마을"],
    "정원": ["정원", "꽃", "화원", "가든"],
    "꽃": ["꽃", "화원", "플라워"],
    "식물": ["식물", "나무", "수목원"],
    "미술관": ["미술관", "전시", "갤러리"],
    "전시": ["전시", "미술관", "갤러리"],
    "건축": ["건축", "건물"],
    "유산": ["유산", "유적", "옛"],
    "농어촌": ["어촌", "농촌", "시골", "바닷마을"],
    "청정": ["청정", "깨끗", "조용", "한적", "평화"],
    "절경": ["절경", "경치", "멋진", "장관"],
    "바위": ["바위", "기암", "암석"],
    "일출": ["일출", "해돋이", "아침", "새벽"],
    "계단식논": ["다랭이", "계단식", "논"],
    "드라마촬영지": ["드라마", "촬영지", "정년이"],
    "정년이": ["정년이"],
    "가족": ["가족", "엄마", "아빠", "부모", "부모님", "아들", "딸"],
    "연인": ["연인", "애인", "커플", "남친", "여친", "데이트"],
    "아이와함께": ["아이", "아기", "애기", "자녀", "아이와"],
    "반려동물": ["강아지", "반려", "댕댕", "고양이"],
    "야생화": ["야생화", "들꽃"],
}


def _extract_terms(text):
    terms = set()
    for tag, triggers in TRIGGER.items():
        if tag in text or any(t in text for t in triggers):
            terms.add(tag)
    return terms


def _binary_cosine(user_terms, place_terms):
    if not user_terms or not place_terms:
        return 0.0
    inter = len(user_terms & place_terms)
    return inter / math.sqrt(len(user_terms) * len(place_terms))


class StationRecommender:
    """JSON을 1회 로드하고, 장소 임베딩을 미리 계산해 캐싱한다."""

    def __init__(self, data_path, model_name=MODEL_NAME):
        with open(data_path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.model_name = model_name

        # (station, place) 쌍을 평탄화
        #  - recommendable 키가 명시적으로 False 인 정류장만 제외(옛 데이터 호환)
        #  - 장소 목록은 places(옛) 또는 attractions(새) 어느 쪽이든 지원
        self.items = []
        for st in self.data["stations"]:
            if st.get("recommendable") is False:
                continue
            for pl in (st.get("places") or st.get("attractions") or []):
                self.items.append((st, pl))

        # 정류장 운행 순서(데이터 등장 순서 = 노선 순서)
        self._stop_order = [self._stop_name(st) for st in self.data["stations"]]

        self._model = None
        self._np = None
        self._place_vecs = None
        self.use_embedding = False
        self._init_model()

    # ---- 공통 헬퍼 -------------------------------------------------------
    @staticmethod
    def _stop_name(station):
        """정류장 이름 — stop(옛) / stop_name(새) 어느 쪽이든."""
        return station.get("stop") or station.get("stop_name") or ""

    @staticmethod
    def _place_tags(place):
        """장소 태그 — keywords(옛) / categories(새) 어느 쪽이든."""
        return place.get("keywords") or place.get("categories") or []

    # ---- 임베딩 준비 -----------------------------------------------------
    @classmethod
    def _place_text(cls, place):
        """임베딩에 넣을 장소 텍스트(이름+설명+키워드/카테고리+유형)."""
        name = place.get("name", "")
        desc = place.get("description", "")
        kws = ", ".join(cls._place_tags(place))
        ptype = place.get("type", "")
        return f"{name}. {desc} 유형: {ptype} 분위기/키워드: {kws}"

    def _init_model(self):
        # RECOMMEND_ENGINE=keyword 이면 임베딩 모델을 아예 로드하지 않고
        # 키워드 폴백으로 동작한다(모델 캐시 잠금/네트워크 문제 회피용).
        if os.environ.get("RECOMMEND_ENGINE", "").lower() == "keyword":
            print("[recommend] RECOMMEND_ENGINE=keyword → 키워드 엔진 사용")
            self.use_embedding = False
            return
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            self._np = np
            self._model = SentenceTransformer(self.model_name)
            texts = [self._place_text(pl) for _, pl in self.items]
            # normalize 해두면 내적 = 코사인 유사도
            self._place_vecs = self._model.encode(
                texts, normalize_embeddings=True, convert_to_numpy=True
            )
            self.use_embedding = True
            print(f"[recommend] 임베딩 엔진 사용: {self.model_name}")
        except Exception as e:  # 설치/다운로드 실패 등
            print(f"[recommend] 임베딩 모델 로드 실패 → 키워드 폴백 사용 ({e})")
            self.use_embedding = False

    # ---- 점수 계산 -------------------------------------------------------
    def _embed_scores(self, text):
        q = self._model.encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
        sims = self._place_vecs @ q  # (N,) 코사인 유사도
        return [float(s) for s in sims]

    def _keyword_scores(self, text):
        user_terms = _extract_terms(text)
        scores = []
        for _, pl in self.items:
            # '감성·사진' 같은 복합 카테고리는 '·'로 쪼개 트리거 사전과 맞춘다
            raw = self._place_tags(pl)
            tags = set()
            for t in raw:
                for part in str(t).replace("/", "·").split("·"):
                    if part.strip():
                        tags.add(part.strip())
            scores.append(_binary_cosine(user_terms, tags))
        return scores, user_terms

    # ---- 메인 추천 -------------------------------------------------------
    def recommend(self, text, top_n=4):
        text = (text or "").strip()
        user_terms = None
        if self.use_embedding:
            scores = self._embed_scores(text)
        else:
            scores, user_terms = self._keyword_scores(text)

        # 정류장별 '대표 장소 1곳'(최고 점수)만 남김
        best = {}  # stop_id -> dict
        for (st, pl), sim in zip(self.items, scores):
            sid = st["stop_id"]
            if sid not in best or sim > best[sid]["similarity"]:
                best[sid] = {"station": st, "place": pl, "similarity": sim}

        # 정류장 단위 상위 top_n
        ranked = sorted(best.values(), key=lambda x: x["similarity"], reverse=True)[:top_n]

        # 버스 정류장 운행 순서대로 정렬 (데이터 등장 순서 기준)
        stop_order = (
            self.data.get("bus_schedule", {}).get("stop_order")
            or self._stop_order
        )

        def order_idx(stop):
            return stop_order.index(stop) if stop in stop_order else 999

        ranked.sort(key=lambda x: order_idx(self._stop_name(x["station"])))

        places = []
        for i, row in enumerate(ranked, start=1):
            st, pl = row["station"], row["place"]
            tags = self._place_tags(pl)
            places.append({
                "key": f"place{i}",            # place1 ~ place4 로 통일
                "order": i,
                "stop": self._stop_name(st),
                "stop_id": st.get("stop_id"),
                "name": pl["name"],
                "address": pl.get("address"),
                "lat": pl.get("lat"),
                "lng": pl.get("lng"),
                "stay_min": pl.get("stay_min"),
                "categories": pl.get("categories", []),
                "keywords": tags,
                "type": pl.get("type"),
                "rating": pl.get("rating"),
                "description": pl.get("description"),
                "note": pl.get("note"),
                "similarity": round(float(row["similarity"]), 4),
            })

        return {
            "engine": "embedding" if self.use_embedding else "keyword",
            "user_terms": sorted(user_terms) if user_terms else None,
            "places": places,
        }
