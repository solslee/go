#!/usr/bin/env python3
"""이번 주말 서울 송파구 20km 안에서 열리는 행사 골라주는 스크립트.

사용법:
    set SEOUL_API_KEY=발급받은키
    python weekend.py

    또는 python weekend.py 발급받은키

인증키 발급(무료, 즉시): https://data.seoul.go.kr/together/mypage/actKey.do
자체 검사:  python weekend.py --test
"""

import json
import math
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, timedelta

# 송파구청
ORIGIN = (37.51450, 127.10660)
RADIUS_KM = 20.0
API = "http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{start}/{end}/"
PAGE = 1000
MAX_PAGES = 20
OUT = "index.html"
KEYFILE = "key.txt"  # 인증키를 채팅에 붙이지 않으려면 이 파일에 한 줄로 저장


def haversine(a, b):
    """두 (위도, 경도) 사이 거리 km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def upcoming_weekend(today):
    """다가오는(또는 진행 중인) 토요일, 일요일."""
    wd = today.weekday()  # 월=0 … 일=6
    if wd == 5:
        sat = today
    elif wd == 6:
        sat = today - timedelta(days=1)
    else:
        sat = today + timedelta(days=5 - wd)
    return sat, sat + timedelta(days=1)


def parse_day(s):
    """'2026-08-01 00:00:00.0' → date. 못 읽으면 None."""
    try:
        y, m, d = s[:10].split("-")
        return date(int(y), int(m), int(d))
    except (AttributeError, ValueError):
        return None


def overlaps(start, end, sat, sun):
    """행사 기간이 주말과 겹치나. 날짜 못 읽은 쪽은 열린 구간으로 취급."""
    if start and start > sun:
        return False
    if end and end < sat:
        return False
    return True


def coords(row):
    """(위도, 경도) 또는 None.

    이 API는 LAT/LOT 값이 뒤바뀐 행이 섞여 있다. 서울은 경도(127)가
    위도(37)보다 항상 크므로 크기로 판별한다.
    """
    try:
        a, b = float(row.get("LAT") or 0), float(row.get("LOT") or 0)
    except (TypeError, ValueError):
        return None
    if not a or not b:
        return None
    return (a, b) if a < b else (b, a)


def fetch(key):
    rows = []
    for page in range(MAX_PAGES):
        start = page * PAGE + 1
        url = API.format(key=key, start=start, end=start + PAGE - 1)
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        info = body.get("culturalEventInfo", body)
        result = info.get("RESULT") or body.get("RESULT") or {}
        # 인증키 오류도 200으로 오고 row만 비어 있어서, 코드를 직접 확인한다.
        if result.get("CODE", "INFO-000") != "INFO-000":
            raise SystemExit("API 오류 {}: {}".format(
                result.get("CODE"), result.get("MESSAGE", "")))
        if "culturalEventInfo" not in body:
            raise SystemExit("예상 못한 응답: {}".format(str(body)[:300]))
        batch = info.get("row") or []
        rows += batch
        total = int(info.get("list_total_count", 0))
        if not batch or len(rows) >= total:
            break
    return rows


def pick(rows, sat, sun):
    """주말·거리 조건 통과한 행사만 화면에 쓸 형태로."""
    out = []
    for r in rows:
        start, end = parse_day(r.get("STRTDATE")), parse_day(r.get("END_DATE"))
        if not overlaps(start, end, sat, sun):
            continue
        c = coords(r)
        dist = haversine(ORIGIN, c) if c else None
        if dist is not None and dist > RADIUS_KM:
            continue
        fee = (r.get("USE_FEE") or "").strip()
        out.append({
            "title": (r.get("TITLE") or "").strip(),
            "cat": (r.get("CODENAME") or "기타").strip(),
            "gu": (r.get("GUNAME") or "").strip(),
            "place": (r.get("PLACE") or "").strip(),
            "when": (r.get("DATE") or "").strip(),
            "target": (r.get("USE_TRGT") or "").strip(),
            "fee": fee,
            "free": not fee or "무료" in fee,
            "img": (r.get("MAIN_IMG") or "").strip(),
            "link": (r.get("ORG_LINK") or "").strip(),
            "ticket": (r.get("TICKET") or "").strip(),
            "dist": None if dist is None else round(dist, 1),
        })
    out.sort(key=lambda e: (e["dist"] is None, e["dist"] or 0))
    return out


# ---------------------------------------------------------------- HTML

TEMPLATE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>이번 주말 뭐하지</title>
<style>
:root{--bg:#fbfaf8;--card:#fff;--fg:#1a1a1a;--dim:#6b6b6b;--line:#e6e3dd;--accent:#d2483c;--chip:#f0ede8}
@media(prefers-color-scheme:dark){:root{--bg:#14140f;--card:#1e1e19;--fg:#f0eee9;--dim:#9a978f;--line:#32322b;--accent:#ff7a5c;--chip:#2a2a23}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--dim);margin:0 0 26px}
.roll{background:var(--accent);color:#fff;border:0;border-radius:12px;padding:15px 26px;
  font-size:17px;font-weight:700;cursor:pointer;font-family:inherit}
.roll:active{transform:translateY(1px)}
#picked{margin:24px 0 0;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
#picked:empty{display:none}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:34px 0 20px;
  padding-top:26px;border-top:1px solid var(--line)}
.chip{background:var(--chip);border:1px solid transparent;color:var(--fg);border-radius:999px;
  padding:7px 14px;font-size:14px;cursor:pointer;font-family:inherit}
.chip.on{background:var(--fg);color:var(--bg)}
.spacer{flex:1}
select{background:var(--chip);color:var(--fg);border:1px solid var(--line);border-radius:8px;
  padding:7px 10px;font-family:inherit;font-size:14px}
label.tog{display:flex;gap:6px;align-items:center;font-size:14px;color:var(--dim);cursor:pointer}
#grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.c{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;
  display:flex;flex-direction:column}
.c.hl{border-color:var(--accent);border-width:2px}
.c img{width:100%;aspect-ratio:3/4;object-fit:cover;background:var(--chip);display:block}
.c .body{padding:14px 15px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.tags{display:flex;flex-wrap:wrap;gap:5px}
.t{font-size:11px;padding:2px 7px;border-radius:5px;background:var(--chip);color:var(--dim)}
.t.free{background:var(--accent);color:#fff}
.c h3{font-size:16px;margin:2px 0 0;line-height:1.35}
.meta{font-size:13px;color:var(--dim);margin:0}
.c a{margin-top:auto;padding-top:8px;font-size:13px;color:var(--accent);text-decoration:none}
.none{color:var(--dim);padding:40px 0}
</style></head><body><div class="wrap">
<h1>이번 주말 뭐하지</h1>
<p class="sub">__SUB__</p>
<button class="roll" onclick="roll()">🎲 뭐할지 골라줘</button>
<div id="picked"></div>
<div class="bar">
  <span id="chips"></span>
  <span class="spacer"></span>
  <label class="tog"><input type="checkbox" id="freeonly" onchange="render()">무료만</label>
  <select id="sort" onchange="render()">
    <option value="dist">가까운 순</option>
    <option value="title">이름 순</option>
  </select>
</div>
<div id="grid"></div>
</div><script>
const EVENTS = __DATA__;
let cat = "전체";

const cats = ["전체", ...[...new Set(EVENTS.map(e => e.cat))].sort()];
document.getElementById("chips").innerHTML = cats.map(c =>
  `<button class="chip${c === "전체" ? " on" : ""}" data-c="${c}">${c}</button>`).join("");
document.getElementById("chips").onclick = ev => {
  if (!ev.target.dataset.c) return;
  cat = ev.target.dataset.c;
  document.querySelectorAll("#chips .chip").forEach(b => b.classList.toggle("on", b.dataset.c === cat));
  render();
};

function visible() {
  const free = document.getElementById("freeonly").checked;
  let list = EVENTS.filter(e => (cat === "전체" || e.cat === cat) && (!free || e.free));
  if (document.getElementById("sort").value === "title")
    list = [...list].sort((a, b) => a.title.localeCompare(b.title, "ko"));
  return list;
}

function card(e, hl) {
  const img = e.img ? `<img src="${e.img}" alt="" loading="lazy">` : "";
  const dist = e.dist === null ? "위치 미정" : e.dist + "km";
  const tags = [e.cat, e.free ? "무료" : e.fee].filter(Boolean)
    .map((t, i) => `<span class="t${i === 1 && e.free ? " free" : ""}">${t}</span>`).join("");
  const link = e.link ? `<a href="${e.link}" target="_blank" rel="noopener">자세히 보기 →</a>` : "";
  return `<div class="c${hl ? " hl" : ""}">${img}<div class="body">
    <div class="tags">${tags}</div><h3>${e.title}</h3>
    <p class="meta">${[e.gu, e.place].filter(Boolean).join(" · ")}</p>
    <p class="meta">${dist} · ${e.when}</p>${link}</div></div>`;
}

function render() {
  const list = visible();
  document.getElementById("grid").innerHTML = list.length
    ? list.map(e => card(e, false)).join("")
    : `<p class="none">조건에 맞는 행사가 없다. 필터를 풀어보자.</p>`;
}

function roll() {
  const pool = [...visible()];
  const out = [];
  while (out.length < 3 && pool.length) out.push(...pool.splice(Math.random() * pool.length | 0, 1));
  document.getElementById("picked").innerHTML = out.map(e => card(e, true)).join("");
}

render();
</script></body></html>
"""


def build_html(events, sat, sun):
    sub = "{}(토) ~ {}(일) · 송파구 기준 {:.0f}km 안 · 총 {}개".format(
        sat.strftime("%m월 %d일"), sun.strftime("%m월 %d일"), RADIUS_KM, len(events))
    data = json.dumps(events, ensure_ascii=False).replace("</", r"<\/")
    return TEMPLATE.replace("__SUB__", sub).replace("__DATA__", data)


# ---------------------------------------------------------------- 포스터 인라인

IMG_MAX = 250_000     # 포스터 1장 허용 크기
IMG_BUDGET = 5_000_000  # 페이지 전체 포스터 예산


def inline_images(events):
    """포스터를 data URI로 박아넣는다.

    Artifact는 CSP로 외부 호스트를 막으므로 원격 이미지가 뜨지 않는다.
    너무 크거나 실패한 건 그냥 이미지 없이 두면 카드가 텍스트만 나온다.
    """
    import base64
    used = 0
    for e in events:
        url = e["img"]
        if not url.startswith("http"):
            e["img"] = ""
            continue
        if used > IMG_BUDGET:
            e["img"] = ""
            continue
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                blob = r.read(IMG_MAX + 1)
                mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        except Exception:
            e["img"] = ""
            continue
        if len(blob) > IMG_MAX or not mime.startswith("image/"):
            e["img"] = ""
            continue
        e["img"] = "data:{};base64,{}".format(mime, base64.b64encode(blob).decode())
        used += len(e["img"])
    kept = sum(1 for e in events if e["img"])
    print("포스터 {}장 내장 ({:.1f}MB)".format(kept, used / 1e6))
    return events


# ---------------------------------------------------------------- 미리보기

def demo_rows(sat):
    """--demo용 가짜 응답. 실제 API 필드명 그대로 쓴다."""
    def img(a, b):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400">'
               '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
               '<stop offset="0" stop-color="{}"/><stop offset="1" stop-color="{}"/>'
               '</linearGradient></defs><rect width="300" height="400" fill="url(#g)"/>'
               '</svg>').format(a, b)
        return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)

    d = sat.strftime("%Y-%m-%d")
    end = (sat + timedelta(days=90)).strftime("%Y-%m-%d")
    return [
        {"TITLE": "서울사진축제 《도시의 표면》", "CODENAME": "전시/미술", "GUNAME": "중구",
         "PLACE": "서울시립미술관", "DATE": d + "~" + end, "USE_TRGT": "누구나",
         "USE_FEE": "무료", "MAIN_IMG": img("#5b6ee1", "#22243f"),
         "ORG_LINK": "https://sema.seoul.go.kr", "TICKET": "현장방문",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": end + " 00:00:00.0",
         "LAT": "37.5640", "LOT": "126.9750"},
        {"TITLE": "한강 달빛야시장", "CODENAME": "축제-기타", "GUNAME": "광진구",
         "PLACE": "뚝섬한강공원", "DATE": d + "~" + d, "USE_TRGT": "누구나",
         "USE_FEE": "", "MAIN_IMG": img("#e8804a", "#5c2a1f"),
         "ORG_LINK": "https://hangang.seoul.go.kr", "TICKET": "",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "127.0668", "LOT": "37.5297"},  # 좌표 뒤바뀐 행
        {"TITLE": "올림픽공원 재즈 피크닉", "CODENAME": "콘서트", "GUNAME": "송파구",
         "PLACE": "올림픽공원 88잔디마당", "DATE": d + "~" + d, "USE_TRGT": "누구나",
         "USE_FEE": "전석 45,000원", "MAIN_IMG": img("#3f8f6f", "#16332a"),
         "ORG_LINK": "https://www.ksponco.or.kr", "TICKET": "예매필요",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "37.5202", "LOT": "127.1215"},
        {"TITLE": "국립중앙박물관 특별전 《유리》", "CODENAME": "전시/미술", "GUNAME": "용산구",
         "PLACE": "국립중앙박물관 기획전시실", "DATE": d + "~" + end, "USE_TRGT": "누구나",
         "USE_FEE": "무료", "MAIN_IMG": img("#8a7bd8", "#2c2545"),
         "ORG_LINK": "https://www.museum.go.kr", "TICKET": "현장방문",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": end + " 00:00:00.0",
         "LAT": "37.5240", "LOT": "126.9803"},
        {"TITLE": "서울숲 플리마켓 & 버스킹", "CODENAME": "축제-기타", "GUNAME": "성동구",
         "PLACE": "서울숲 가족마당", "DATE": d + "~" + d, "USE_TRGT": "누구나",
         "USE_FEE": "무료", "MAIN_IMG": img("#6fae4a", "#20301a"),
         "ORG_LINK": "https://seoulforest.or.kr", "TICKET": "",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "37.5445", "LOT": "127.0374"},
        {"TITLE": "DDP 디자인 페어", "CODENAME": "전시/미술", "GUNAME": "중구",
         "PLACE": "동대문디자인플라자 배움터", "DATE": d + "~" + end, "USE_TRGT": "누구나",
         "USE_FEE": "성인 12,000원", "MAIN_IMG": img("#4aa6b8", "#173239"),
         "ORG_LINK": "https://www.ddp.or.kr", "TICKET": "예매필요",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": end + " 00:00:00.0",
         "LAT": "37.5665", "LOT": "127.0092"},
        {"TITLE": "북서울꿈의숲 어린이 마술극", "CODENAME": "아동", "GUNAME": "강북구",
         "PLACE": "북서울꿈의숲 아트센터", "DATE": d + "~" + d, "USE_TRGT": "3세 이상",
         "USE_FEE": "10,000원", "MAIN_IMG": img("#d05a8a", "#3a1a28"),
         "ORG_LINK": "https://dreamforest.seoul.go.kr", "TICKET": "예매필요",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "37.6205", "LOT": "127.0554"},
        {"TITLE": "잠실 실내 클라이밍 원데이 클래스", "CODENAME": "교육/체험", "GUNAME": "송파구",
         "PLACE": "잠실종합운동장", "DATE": d + "~" + d, "USE_TRGT": "성인",
         "USE_FEE": "25,000원", "MAIN_IMG": "",  # 사진 없는 행
         "ORG_LINK": "", "TICKET": "예매필요",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "37.5150", "LOT": "127.0730"},
        {"TITLE": "정보 미비 행사 (좌표 없음)", "CODENAME": "기타", "GUNAME": "강동구",
         "PLACE": "강동아트센터", "DATE": d + "~" + d, "USE_TRGT": "누구나",
         "USE_FEE": "무료", "MAIN_IMG": "", "ORG_LINK": "", "TICKET": "",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "", "LOT": ""},
        {"TITLE": "김포공항 근처 행사 (20km 밖, 걸러져야 함)", "CODENAME": "기타",
         "GUNAME": "강서구", "PLACE": "강서구청", "DATE": d, "USE_TRGT": "누구나",
         "USE_FEE": "무료", "MAIN_IMG": "", "ORG_LINK": "", "TICKET": "",
         "STRTDATE": d + " 00:00:00.0", "END_DATE": d + " 00:00:00.0",
         "LAT": "37.5510", "LOT": "126.8495"},
    ]


# ---------------------------------------------------------------- 자체 검사

def test():
    # 강서구청은 20km 밖, 잠실역은 안쪽
    assert haversine(ORIGIN, (37.5510, 126.8495)) > RADIUS_KM
    assert haversine(ORIGIN, (37.5133, 127.1000)) < 2

    # 주말 계산: 월요일·금요일은 다가오는 토/일, 일요일은 진행 중인 주말
    assert upcoming_weekend(date(2026, 8, 3)) == (date(2026, 8, 8), date(2026, 8, 9))
    assert upcoming_weekend(date(2026, 8, 7)) == (date(2026, 8, 8), date(2026, 8, 9))
    assert upcoming_weekend(date(2026, 8, 8)) == (date(2026, 8, 8), date(2026, 8, 9))
    assert upcoming_weekend(date(2026, 8, 9)) == (date(2026, 8, 8), date(2026, 8, 9))

    sat, sun = date(2026, 8, 8), date(2026, 8, 9)
    assert overlaps(date(2026, 1, 1), date(2026, 12, 31), sat, sun)   # 장기 전시
    assert overlaps(date(2026, 8, 9), date(2026, 8, 9), sat, sun)     # 일요일 단일
    assert not overlaps(date(2026, 8, 10), date(2026, 8, 11), sat, sun)  # 주말 지난 뒤
    assert not overlaps(date(2026, 8, 1), date(2026, 8, 7), sat, sun)    # 금요일 종료
    assert overlaps(None, None, sat, sun)                             # 날짜 없음 → 포함

    # 좌표 뒤바뀐 행도 바로잡는다
    assert coords({"LAT": "37.5", "LOT": "127.1"}) == (37.5, 127.1)
    assert coords({"LAT": "127.1", "LOT": "37.5"}) == (37.5, 127.1)
    assert coords({"LAT": "", "LOT": "127.1"}) is None

    print("검사 통과")


def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--test" in flags:
        return test()

    demo = "--demo" in flags
    key = args[0] if args else os.environ.get("SEOUL_API_KEY", "").strip()
    if not key and os.path.exists(KEYFILE):
        with open(KEYFILE, encoding="utf-8") as f:
            key = f.read().strip()
    if not key and not demo:
        raise SystemExit(
            "서울시 열린데이터광장 인증키가 필요하다.\n"
            "  발급(무료, 즉시): https://data.seoul.go.kr/together/mypage/actKey.do\n"
            "  키 주는 방법 (아무거나 하나):\n"
            "    1) key.txt 파일에 키만 한 줄로 저장\n"
            "    2) set SEOUL_API_KEY=발급받은키\n"
            "    3) python weekend.py 발급받은키\n"
            "  키 없이 화면만 보려면: python weekend.py --demo")

    sat, sun = upcoming_weekend(date.today())
    print("{} ~ {} 행사 찾는 중...".format(sat, sun))
    rows = demo_rows(sat) if demo else fetch(key)
    events = pick(rows, sat, sun)
    print("{}개 찾음".format(len(events)))

    path = os.path.abspath(OUT)
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(events, sat, sun))
    print(path)
    webbrowser.open("file:///" + path.replace("\\", "/"))


if __name__ == "__main__":
    main()
