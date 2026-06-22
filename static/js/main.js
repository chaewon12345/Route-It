// 남해 뚜벅이버스 — 와이어프레임 v4 플로우 + 실제 백엔드 연동
(function () {
  const wf = document.querySelector(".wf");
  const stage = wf.querySelector("#wfStage");
  const screens = wf.querySelectorAll("[data-screen]");
  const dots = wf.querySelectorAll(".sd");
  const backBtn = wf.querySelector("#wfBack");
  const ledEl = wf.querySelector("#wfLed");
  const prog = wf.querySelector("#wfProg");

  const LED = { input: "코스 만들기", analyze: "분석 중...", keywords: "키워드 추출", stops: "정류장 찾기", route: "버스 코스", kakao: "정류장 지도" };
  const IDX = { input: 0, analyze: 1, keywords: 2, stops: 3, route: 4, kakao: 5 };
  const BACK = { analyze: "input", keywords: "input", stops: "keywords", route: "stops", kakao: "route" };

  // 정류장 위치별로 "버스 타는 회차" 매핑 — [일차][정류장순서]
  //  1일차 1번째 → 2회차, 1일차 2번째 → 3회차
  //  2일차 1번째 → 1회차, 2일차 2번째 → 2회차
  const BOARD = [["2회차", "3회차"], ["1회차", "2회차"]];

  const CAT_ICON = {
    "카페": "ti-coffee", "자연·힐링": "ti-trees", "감성·사진": "ti-camera",
    "체험·액티비티": "ti-walk", "역사·문화": "ti-building-monument",
    "미술관": "ti-palette", "박물관": "ti-building-bank",
  };
  const THUMB_BG = ["var(--green)", "var(--amber)", "#4F8F3F", "#3F77A0"];

  // 가상 지도 배경(장식용 SVG)
  const FAKE_MAP_SVG = `<svg viewBox="0 0 360 240" preserveAspectRatio="xMidYMid slice" style="position:absolute;inset:0;width:100%;height:100%">
    <rect width="360" height="240" fill="#E7EFDC"/>
    <path d="M44 0 L70 240" stroke="#fff" stroke-width="10"/><path d="M44 0 L70 240" stroke="#F2C94C" stroke-width="2"/>
    <path d="M0 86 L360 64" stroke="#fff" stroke-width="10"/>
    <path d="M0 188 L360 196" stroke="#fff" stroke-width="9"/>
    <path d="M214 0 L246 240" stroke="#fff" stroke-width="7"/>
    <rect x="82" y="22" width="46" height="34" rx="4" fill="#D6E3C7"/><rect x="152" y="24" width="40" height="30" rx="4" fill="#D6E3C7"/>
    <rect x="262" y="32" width="50" height="38" rx="4" fill="#D6E3C7"/><rect x="92" y="104" width="48" height="40" rx="4" fill="#D6E3C7"/>
    <rect x="252" y="104" width="46" height="44" rx="4" fill="#D6E3C7"/>
    <rect x="96" y="206" width="50" height="26" rx="4" fill="#D6E3C7"/><rect x="270" y="208" width="48" height="24" rx="4" fill="#D6E3C7"/>
  </svg>`;

  let cur = "input", timer = null, checkTimers = [];
  let places = [];
  let scheduleById = {};      // stop_id -> {1회차:..}
  let scheduleStops = [];     // [{stop_id, stop_name, schedule}]

  function show(name) {
    cur = name;
    screens.forEach((s) => s.classList.toggle("active", s.dataset.screen === name));
    backBtn.style.visibility = name === "input" ? "hidden" : "visible";
    ledEl.textContent = LED[name] || "뚜벅이버스";
    dots.forEach((d, i) => d.classList.toggle("on", i === IDX[name]));
    if (timer) { clearTimeout(timer); timer = null; }
  }

  // 분석 화면의 3단계 체크를 순서대로 천천히 완료 표시
  function runChecks() {
    checkTimers.forEach(clearTimeout);
    checkTimers = [];
    const checks = wf.querySelectorAll("[data-chk]");
    checks.forEach((c) => { c.classList.remove("done"); const i = c.querySelector("i"); if (i) i.className = "ti ti-circle"; });
    const delays = [1000, 2300, 3500];   // 약 4초 안에 순차 완료
    checks.forEach((c, k) => {
      checkTimers.push(setTimeout(() => {
        c.classList.add("done");
        const i = c.querySelector("i");
        if (i) i.className = "ti ti-circle-check";
      }, delays[k] || (k + 1) * 1000));
    });
  }

  // ---- 1) 입력 → 분석 → 추천 fetch -----------------------------------------
  async function startAnalyze() {
    const text = wf.querySelector("#wfInput").value.trim();
    const errEl = wf.querySelector("#wfErr");
    errEl.style.display = "none";
    if (!text) { errEl.textContent = "여행 느낌을 한 문장 적어주세요."; errEl.style.display = "block"; return; }

    show("analyze");
    prog.style.width = "6%";
    void prog.offsetWidth;
    requestAnimationFrame(() => { prog.style.width = "100%"; });

    runChecks();
    const minWait = new Promise((r) => setTimeout(r, 4000));
    try {
      const [recRes] = await Promise.all([
        fetch("/api/recommend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        }).then((r) => r.json()),
        loadSchedule(),
        minWait,
      ]);
      if (recRes.error) throw new Error(recRes.error);
      places = recRes.places || [];
      if (!places.length) throw new Error("어울리는 정류장을 찾지 못했어요. 문장을 바꿔보세요.");
      renderKeywords();
      renderStops();
      renderRoute();
      show("keywords");
    } catch (e) {
      show("input");
      errEl.textContent = "오류: " + e.message;
      errEl.style.display = "block";
    }
  }

  async function loadSchedule() {
    try {
      const data = await fetch("/api/schedule").then((r) => r.json());
      scheduleStops = data.stops || [];
      scheduleById = {};
      scheduleStops.forEach((s) => { scheduleById[s.stop_id] = s.schedule || {}; });
    } catch (_) { scheduleStops = []; scheduleById = {}; }
  }

  // ---- 2) 키워드 -----------------------------------------------------------
  function renderKeywords() {
    const tags = [];
    const seen = new Set();
    places.forEach((p) => (p.keywords || []).forEach((kw) => {
      String(kw).replace(/\//g, "·").split("·").forEach((t) => {
        const v = t.trim();
        if (v && !seen.has(v)) { seen.add(v); tags.push(v); }
      });
    }));
    const box = wf.querySelector("#kwList");
    box.innerHTML = tags.slice(0, 8).map((t, i) =>
      `<span class="pill ${i % 2 ? "p-amber" : "p-green"}">${esc(t)}</span>`
    ).join("") || `<span class="empty">키워드를 찾지 못했어요.</span>`;
  }

  // ---- 3) 정류장 카드 ------------------------------------------------------
  function renderStops() {
    const box = wf.querySelector("#stopList");
    box.innerHTML = places.map((p, i) => {
      const cat = (p.keywords || [])[0] || "";
      const icon = CAT_ICON[cat] || "ti-map-pin";
      const bg = THUMB_BG[i % THUMB_BG.length];
      const pct = Math.round((p.similarity || 0) * 100);
      const tag = (p.keywords || []).slice(0, 2).join(" · ") || (p.type || "");
      return `<div class="pcard">
        <span class="stopno">${i + 1}</span>
        <div class="thumb" style="background:${bg}"><i class="ti ${icon}" aria-hidden="true"></i></div>
        <div><div class="jua" style="font-size:13px">${esc(p.stop)}</div><div class="tag">${esc(tag)}</div></div>
        <span class="match">${pct}%</span>
      </div>`;
    }).join("");
  }

  // ---- 4) 1박2일 코스 ------------------------------------------------------
  // 특정 정류장이 (di 일차, j 번째)일 때 타는 버스 시간 — 그 정류장 고유 schedule에서 조회
  function boardInfo(place, di, j) {
    const key = (BOARD[di] && BOARD[di][j]) || null;
    const sched = scheduleById[place.stop_id] || {};
    const time = key ? sched[key] || null : null;
    return { key, time };
  }

  function terminalStop() {
    return scheduleStops.find((s) => /터미널/.test(s.stop_name || "")) || null;
  }
  function terminalTime(key) {
    const t = terminalStop();
    return t && t.schedule ? t.schedule[key] || null : null;
  }

  function renderRoute() {
    // 상단 터미널 시간표 요약
    const term = terminalStop();
    const tbl = wf.querySelector("#termTbl");
    if (term && term.schedule && Object.keys(term.schedule).length) {
      tbl.innerHTML = `<i class="ti ti-clock-hour-9" aria-hidden="true"></i> 남해공용터미널 ` +
        Object.keys(term.schedule).map((k) => `<span>·<b>${k.replace("회차", "회")}</b> ${term.schedule[k]}</span>`).join("");
    } else {
      tbl.innerHTML = `<i class="ti ti-clock-hour-9" aria-hidden="true"></i> 한 정류장에서 3~4시간 머문 뒤 다음 회차 버스로 이동해요`;
    }

    const half = Math.ceil(places.length / 2);
    const days = [places.slice(0, half), places.slice(half)];
    const dayMeta = [
      { cls: "", icon: "ti-sun", label: "1일차", color: "green" },
      { cls: "d2", icon: "ti-sunrise", label: "2일차", color: "navy2" },
    ];

    const box = wf.querySelector("#routeBox");
    box.innerHTML = days.map((day, di) => {
      if (!day.length) return "";
      const m = dayMeta[di];
      const stopsHtml = day.map((p, j) => {
        const { key, time } = boardInfo(p, di, j);
        const stay = p.stay_min ? `${p.stay_min}분` : "3~4시간";
        const tag = (p.keywords || []).slice(0, 2).join(" · ");
        const hop = key
          ? `<span class="hop"><i class="ti ti-bus" style="font-size:11px" aria-hidden="true"></i> ${key.replace("회차", "회")} ${time || "--:--"}</span>`
          : "";
        return `<div class="rstop" data-stop-idx="${places.indexOf(p)}">
          <i class="ti ti-map-pin gomap" aria-hidden="true"></i>
          <div class="sname"><i class="ti ti-bus-stop" style="color:var(--${m.color})" aria-hidden="true"></i> ${esc(p.stop)} ${hop}</div>
          <div class="stay"><i class="ti ti-clock" aria-hidden="true"></i> ${stay} · ${esc(p.name)}${tag ? " (" + esc(tag) + ")" : ""}</div>
        </div>`;
      }).join("");

      let topBar = "", bottomBar = "";
      if (di === 0) {
        // 1일차: 상단 출발
        const t = terminalTime(BOARD[0][0]);
        topBar = `<div class="depart"><i class="ti ti-building-bridge" aria-hidden="true"></i> 남해공용터미널 출발${t ? `<span class="t">${t}</span>` : ""}</div>`;
        bottomBar = `<div class="endbar"><i class="ti ti-moon" aria-hidden="true"></i> ${esc(day[day.length - 1].stop)} 부근에서 1박</div>`;
      } else {
        // 2일차: 상단 출발 없음, 하단 도착
        const lastKey = BOARD[1][Math.min(day.length, BOARD[1].length) - 1];
        const t = terminalTime(lastKey);
        bottomBar = `<div class="depart arrive"><i class="ti ti-flag" aria-hidden="true"></i> 남해공용터미널 도착${t ? `<span class="t">${t}</span>` : ""}</div>`;
      }

      return `<div>
        <div class="dayhead ${m.cls}"><i class="ti ${m.icon}" aria-hidden="true"></i> ${m.label} · ${day.length}개 정류장</div>
        <div class="daybox">${topBar}${stopsHtml}${bottomBar}</div>
      </div>`;
    }).join("");

    box.querySelectorAll("[data-stop-idx]").forEach((el) => {
      el.addEventListener("click", () => {
        const p = places[+el.dataset.stopIdx];
        if (p) openKakao(p);
      });
    });
  }

  // ---- 5) 지도 화면 (가상 지도 + 실제 음식점/카페 아이콘) -------------------
  async function openKakao(place) {
    wf.querySelector("#kkTitle").textContent = `${place.stop} 정류장 주변`;
    const list = wf.querySelector("#kkList");
    const map = wf.querySelector("#kkMap");
    list.innerHTML = `<div class="empty">불러오는 중…</div>`;
    map.innerHTML = FAKE_MAP_SVG;
    show("kakao");

    if (place.lat == null || place.lng == null) {
      list.innerHTML = `<div class="empty">좌표 정보가 없는 정류장이에요.</div>`;
      return;
    }
    try {
      const url = `/api/nearby?lat=${place.lat}&lng=${place.lng}&radius=2000`;
      const data = await fetch(url).then((r) => r.json());
      if (data.error) throw new Error(data.error);
      const items = data.items || [];
      renderNearbyList(list, items);
      renderFakeMap(place, items);
    } catch (e) {
      list.innerHTML = `<div class="empty">오류: ${esc(e.message)}</div>`;
    }
  }

  function renderNearbyList(box, items) {
    if (!items.length) { box.innerHTML = `<div class="empty">반경 2km 내 결과가 없어요.</div>`; return; }
    box.innerHTML = items.slice(0, 8).map((it) => {
      const isEat = it.category !== "카페";
      const bg = isEat ? "var(--coral)" : "var(--amber)";
      const ic = isEat ? "#fff" : "var(--amberIcon)";
      const icon = isEat ? "ti-tools-kitchen-2" : "ti-coffee";
      const dist = it.distance_m != null ? ` · 약 ${it.distance_m}m` : "";
      return `<div class="near">
        <div class="ic" style="background:${bg};color:${ic}"><i class="ti ${icon}" aria-hidden="true"></i></div>
        <div style="flex:1">
          <div class="nm"><a href="${it.url}" target="_blank" rel="noopener">${esc(it.name)}</a></div>
          <div class="mt">${esc(it.category)}${dist}</div>
        </div>
      </div>`;
    }).join("");
  }

  // 가상 지도 위에 정류장(중심) + 주변 음식점/카페 아이콘을 위치별로 배치
  function renderFakeMap(place, items) {
    const el = wf.querySelector("#kkMap");
    const pts = (items || []).slice(0, 8).filter((it) => it.lat != null && it.lng != null);

    // 실제 위경도 차이를 지도 영역(%)으로 변환 — 상대 방향을 살린다
    let maxd = 0.0008;
    pts.forEach((it) => { maxd = Math.max(maxd, Math.abs(it.lng - place.lng), Math.abs(it.lat - place.lat)); });
    const toXY = (la, ln) => ({
      x: Math.max(9, Math.min(91, 50 + ((ln - place.lng) / maxd) * 36)),
      y: Math.max(26, Math.min(86, 50 - ((la - place.lat) / maxd) * 36)),  // 위도↑ = 위쪽
    });

    const pins = [
      `<div class="vpin stop" style="left:50%;top:50%"><i class="ti ti-bus" aria-hidden="true"></i></div>`,
      `<div class="vlabel" style="left:50%;top:calc(50% + 20px)">${esc(place.stop)} 정류장</div>`,
    ];
    pts.forEach((it) => {
      const { x, y } = toXY(it.lat, it.lng);
      const isEat = it.category !== "카페";
      const icon = isEat ? "ti-tools-kitchen-2" : "ti-coffee";
      pins.push(`<div class="vpin ${isEat ? "eat" : "cafe"}" style="left:${x}%;top:${y}%" title="${esc(it.name)}"><i class="ti ${icon}" aria-hidden="true"></i></div>`);
    });

    el.innerHTML = FAKE_MAP_SVG + pins.join("");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---- 이벤트 바인딩 -------------------------------------------------------
  wf.querySelector("#wfGo").addEventListener("click", startAnalyze);
  wf.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => show(b.dataset.go)));
  backBtn.addEventListener("click", () => show(BACK[cur] || "input"));

  stage.classList.add("ready");
  show("input");
})();
