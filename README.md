# 남해 뚜벅이버스 추천

사용자가 취향·여행스타일·동행을 텍스트로 입력하면, 각 장소의 (이름+설명+키워드)와
**문장 임베딩 코사인 유사도**를 계산해 **서로 다른 4개 정류장**(정류장당 장소 1곳)을
버스 운행 순서대로 골라줍니다. 결과 키는 `place1 ~ place4`로 통일됩니다.
각 장소는 카카오 로컬 API로 **반경 2km 음식점·카페**를 조회할 수 있습니다.

## 디렉토리 구조
```
namhae-trip/
├── app.py                      # Flask 메인 (라우트/카카오 연동)
├── recommend.py                # 임베딩 코사인 추천 엔진 (+ 키워드 폴백)
├── data/
│   └── namhae_stations.json    # 정류장·장소·버스 시간표 데이터
├── templates/
│   └── index.html              # API 테스트 페이지
├── static/
│   ├── css/style.css
│   └── js/main.js
├── requirements.txt
├── .env
└── README.md
```

## VS Code에서 실행하기

1) 폴더 열기: VS Code → File → Open Folder → `namhae-trip`

2) 가상환경 + 패키지 설치 (터미널: Ctrl+`)
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```
> `sentence-transformers`는 처음 실행 시 임베딩 모델(약 수백 MB)을 자동 다운로드합니다.
> 설치/다운로드가 안 되면 자동으로 **키워드 폴백**으로 동작하니 일단 서버는 떠요.

3) 카카오 키 설정 (주변 맛집·카페 검색용)
```bash
cp .env   
# .env 를 열어 KAKAO_REST_API_KEY 값을 채워넣기
```

4) 실행
```bash
python app.py
```
→ 브라우저에서 http://127.0.0.1:5000 접속

## API

### POST /api/recommend
요청
```json
{ "text": "사진 많이 찍고 힐링하러 혼자 가요. 바다도 보고 싶어요." }
```
응답(요약)
```json
{
  "city": "남해",
  "engine": "embedding",
  "places": [
    { "key": "place1", "stop": "동정", "name": "돌창고",
      "lat": 34.809482, "lng": 127.981835, "similarity": 0.61, "...": "..." }
  ]
}
```

### GET /api/nearby?lat=&lng=&radius=2000
좌표 반경(기본 2km) 내 음식점(FD6)·카페(CE7)를 거리순으로 반환.

### GET /api/health
엔진 종류(embedding/keyword), 카카오 키 로드 여부 확인.

## 빠른 동작 확인 (curl)
```bash
curl http://127.0.0.1:5000/api/health

curl -X POST http://127.0.0.1:5000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"text":"사진 많이 찍고 힐링하러 혼자 가요. 바다도 보고 싶어요."}'
```

## 다음 단계
- 프론트에 카카오 지도(JS SDK)를 붙여, place1~4 마커 + 클릭 시 2km 음식점/카페 표시
- 추천 결과를 지도 경로(정류장 순서)로 시각화
