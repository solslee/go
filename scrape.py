#!/usr/bin/env python3
"""서울문화포털(culture.seoul.go.kr)에서 이번 주말 문화행사를 긁어와 index.html을 새로 만든다.

로그인/인증키 없이 공개된 검색 페이지만 사용한다.
GitHub Actions에서 매일 자동 실행하는 걸 전제로 만들었다 (.github/workflows/update.yml).

사용법:
    python scrape.py
"""

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = "https://culture.seoul.go.kr"
LIST_URL = BASE + "/culture/culture/cultureEvent/eventList.do?viewType=CONTBODY"
DETAIL_URL = BASE + "/culture/culture/cultureEvent/view.do?cultcode={code}&menuNo=200110"
HEADERS = {"User-Agent": "Mozilla/5.0 (weekend-seoul auto updater)"}
MAX_PAGES = 60          # 안전장치. 실제로는 훨씬 적은 페이지에서 끝난다.
DETAIL_DELAY = 0.15     # 상세페이지 연속 요청 사이 대기(초). 서버에 부담 안 주려고.
TEMPLATE_FILE = "template.html"
OUT_FILE = "index.html"

CAT_MAP = {
    "공연": "콘서트", "전시": "전시/미술", "축제": "축제-기타",
    "교육/체험": "교육/체험", "기타": "기타",
}

FUNSEOUL_BASE = "https://festival.seoul.go.kr"
FUNSEOUL_CALENDAR_URL = FUNSEOUL_BASE + "/festival/year/loadMap.do"
FUNSEOUL_DETAIL_URL = FUNSEOUL_BASE + "/festival/main/mo/monthDetailList.do"
FUNSEOUL_VIEW_URL = FUNSEOUL_BASE + "/festival/main/festivalView.do?festacode={code}"
FUNSEOUL_CAT_MAP = {
    "문화/예술": "축제-문화/예술", "관광/체육": "스포츠", "기타": "축제-기타",
}


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


def upcoming_weekends_within(today, days=30):
    """오늘부터 days일 안에 걸리는 토/일 쌍을 전부(이번 주말 포함) 반환."""
    sat, _ = upcoming_weekend(today)
    weekends = []
    while (sat - today).days <= days:
        weekends.append((sat, sat + timedelta(days=1)))
        sat += timedelta(days=7)
    return weekends


def fetch(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_list_page(html_text):
    """<li>...</li> 블록마다 cultcode/제목/장소/기간/카테고리/이미지 추출."""
    items = []
    for li in re.findall(r"<li>\s*<a href=\"[^\"]*?\?[^\"]*\".*?</a>\s*</li>", html_text, re.S):
        m_code = re.search(r"cultcode=(\d+)", li)
        m_cate = re.search(r'<span class="cate[^>]*>([^<]+)</span>', li)
        m_img = re.search(r'<img src="([^"]+)"', li)
        m_title = re.search(r'<p class="tit">([^<]*)</p>', li)
        m_date = re.search(r'<div class="date">\s*<span>([^<]*)</span>\s*~\s*<span>([^<]*)</span>', li)
        m_place = re.search(r'<p class="place">([^<]*)</p>', li)
        if not (m_code and m_title):
            continue
        img = m_img.group(1) if m_img else ""
        if "noImg" in img:
            img = ""
        elif img.startswith("/"):
            img = BASE + img
        items.append({
            "cultcode": m_code.group(1),
            "cat_raw": html.unescape(m_cate.group(1)).strip() if m_cate else "기타",
            "title": html.unescape(m_title.group(1)).strip(),
            "place": html.unescape(m_place.group(1)).strip() if m_place else "",
            "sdate": m_date.group(1).strip() if m_date else "",
            "edate": m_date.group(2).strip() if m_date else "",
            "img": img,
        })
    return items


def fetch_weekend_list(sdate, edate, seen):
    """culture.seoul.go.kr에서 sdate~edate와 겹치는 행사를 긁어 seen(cultcode 기준 dict)에 누적한다."""
    for page in range(1, MAX_PAGES + 1):
        body = fetch(LIST_URL, {"menuNo": "200110", "pageIndex": str(page),
                                 "sdate": sdate, "edate": edate})
        items = parse_list_page(body)
        if not items:
            break
        for it in items:
            seen[it["cultcode"]] = it


def parse_detail(cultcode):
    """상세페이지에서 위경도/주소/요금/장소/대상/외부링크를 뽑는다."""
    try:
        body = fetch(DETAIL_URL.format(code=cultcode))
    except Exception:
        return {}

    out = {}
    m = re.search(r"la:'([\-0-9.]+)'", body)
    if m:
        out["lat"] = float(m.group(1))
    m = re.search(r"lo:'([\-0-9.]+)'", body)
    if m:
        out["lon"] = float(m.group(1))
    m = re.search(r'addr:\s*"([^"]*)"', body)
    if m:
        out["addr"] = html.unescape(m.group(1))

    fields = {}
    for label, value in re.findall(
        r'<div class="type-th">\s*<span>([^<]+)</span>\s*</div>\s*'
        r'<div class="type-td">\s*<span>(.*?)</span>\s*</div>\s*</li>', body, re.S):
        value = html.unescape(re.sub(r"\s+", " ", value)).strip()
        fields[label.strip()] = value
    out["fields"] = fields

    m = re.search(r'<div class="detail-btn"[^>]*>\s*<a href="([^"]+)"', body)
    if m:
        out["homepage"] = m.group(1)

    return out


def build_event(item, detail):
    fields = detail.get("fields", {})
    fee = fields.get("요금", "").strip()
    free = (not fee) or ("무료" in fee)
    addr = detail.get("addr", "")
    gu_m = re.search(r"([가-힣]+구)", addr)

    return {
        "id": "c" + item["cultcode"],
        "title": item["title"],
        "cat": CAT_MAP.get(item["cat_raw"], item["cat_raw"]),
        "gu": gu_m.group(1) if gu_m else "",
        "place": fields.get("장소") or item["place"],
        "when": "{}~{}".format(item["sdate"], item["edate"]) if item["sdate"] else "",
        "target": fields.get("대상", ""),
        "fee": fee or "무료",
        "free": free,
        "img": item["img"],
        "link": detail.get("homepage") or DETAIL_URL.format(code=item["cultcode"]),
        "ticket": "",
        "lat": detail.get("lat"),
        "lon": detail.get("lon"),
    }


def fetch_funseoul_events(weekends):
    """펀서울(festival.seoul.go.kr) 캘린더에서 주어진 주말들에 걸리는 축제 코드를 찾아 상세정보를 가져온다."""
    try:
        calendar_html = fetch(FUNSEOUL_CALENDAR_URL)
    except Exception:
        return []

    codes = set()
    for sat, sun in weekends:
        for day in (sat, sun):
            pattern = r'data-event-month="{}" data-event-date="{}" data-event-code="([^"]*)"'.format(
                day.month, day.day)
            for m in re.findall(pattern, calendar_html):
                codes.update(c for c in m.split(",") if c)
    if not codes:
        return []

    try:
        body = fetch(FUNSEOUL_DETAIL_URL, {"items": ",".join(sorted(codes))})
        results = json.loads(body)
    except Exception:
        return []

    events = []
    for r in results or []:
        fee = (r.get("use_fee") or "").strip()
        img_id = r.get("main_img") or ""
        events.append({
            "id": "f" + str(r.get("festa_code")),
            "title": (r.get("festa_name") or "").strip(),
            "cat": FUNSEOUL_CAT_MAP.get(r.get("subjname"), "축제-기타"),
            "gu": r.get("gname") or "",
            "place": r.get("place") or "",
            "when": "{}~{}".format(r["strt_date"], r["end_date"]) if r.get("strt_date") else (r.get("time") or ""),
            "target": r.get("use_trgt") or "",
            "fee": fee or "요금 정보 없음",
            "free": bool(fee) and ("무료" in fee),
            "img": (FUNSEOUL_BASE + "/cmmn/file/getImage.do?isThumb=Y&atchFileId=" + img_id) if img_id else "",
            "link": r.get("homepage") or FUNSEOUL_VIEW_URL.format(code=r.get("festa_code")),
            "ticket": "",
            "lat": None,
            "lon": None,
        })
    return events


def normalize_title(t):
    t = re.sub(r"\[[^\]]*\]", "", t)          # [주최기관] 같은 대괄호 제거
    t = re.sub(r"20\d\d", "", t)               # 연도 제거
    return re.sub(r"[^\w가-힣]", "", t).lower()


def merge_events(primary, extra):
    """primary(문화포털) 기준으로 extra(펀서울)에서 중복(같은 행사)만 걸러내고 합친다."""
    seen = {normalize_title(e["title"]) for e in primary}
    merged = list(primary)
    for e in extra:
        key = normalize_title(e["title"])
        if not key or any(key in s or s in key for s in seen):
            continue
        seen.add(key)
        merged.append(e)
    return merged


def build_sub(weekends, count):
    first_sat = weekends[0][0]
    last_sun = weekends[-1][1]
    return (
        "{} ~ {} (주말 {}개) · <span id=\"originText\">가락시장역</span> 기준 "
        "<span id=\"radiusText\">20</span>km 안 · 총 <span id=\"count\">{}</span>개 · "
        "서울문화포털·펀서울 자동 수집(로그인/API 미사용)"
    ).format(first_sat.strftime("%m월 %d일"), last_sun.strftime("%m월 %d일"), len(weekends), count)


def main():
    weekends = upcoming_weekends_within(date.today(), days=30)
    print("이번 주말 포함 향후 {}개 주말 조회: {}".format(
        len(weekends), ", ".join("{}~{}".format(s.isoformat(), e.isoformat()) for s, e in weekends)))

    seen = {}
    for sat, sun in weekends:
        fetch_weekend_list(sat.isoformat(), sun.isoformat(), seen)
    items = list(seen.values())
    print("문화포털 {}건 발견, 상세정보 가져오는 중...".format(len(items)))

    events = []
    for i, item in enumerate(items):
        detail = parse_detail(item["cultcode"])
        events.append(build_event(item, detail))
        if i % 20 == 0:
            print("  {}/{}".format(i, len(items)))
        time.sleep(DETAIL_DELAY)

    funseoul_events = fetch_funseoul_events(weekends)
    print("펀서울 {}건 발견".format(len(funseoul_events)))
    events = merge_events(events, funseoul_events)
    print("중복 제거 후 총 {}건".format(len(events)))

    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        template = f.read()

    data_json = json.dumps(events, ensure_ascii=False).replace("</", r"<\/")
    out = template.replace("__DATA__", data_json).replace("__SUB__", build_sub(weekends, len(events)))

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)
    print("{}개 행사로 {} 갱신 완료".format(len(events), OUT_FILE))


if __name__ == "__main__":
    main()
