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


def fetch_weekend_list(sdate, edate):
    seen = {}
    for page in range(1, MAX_PAGES + 1):
        body = fetch(LIST_URL, {"menuNo": "200110", "pageIndex": str(page),
                                 "sdate": sdate, "edate": edate})
        items = parse_list_page(body)
        if not items:
            break
        for it in items:
            seen[it["cultcode"]] = it
    return list(seen.values())


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


def build_sub(sat, sun, count):
    return (
        "{}(토) ~ {}(일) · <span id=\"originText\">가락시장역</span> 기준 "
        "<span id=\"radiusText\">20</span>km 안 · 총 <span id=\"count\">{}</span>개 · "
        "서울문화포털 자동 수집(로그인/API 미사용)"
    ).format(sat.strftime("%m월 %d일"), sun.strftime("%m월 %d일"), count)


def main():
    sat, sun = upcoming_weekend(date.today())
    sdate, edate = sat.isoformat(), sun.isoformat()
    print("{} ~ {} 행사 찾는 중...".format(sdate, edate))

    items = fetch_weekend_list(sdate, edate)
    print("{}건 발견, 상세정보 가져오는 중...".format(len(items)))

    events = []
    for i, item in enumerate(items):
        detail = parse_detail(item["cultcode"])
        events.append(build_event(item, detail))
        if i % 20 == 0:
            print("  {}/{}".format(i, len(items)))
        time.sleep(DETAIL_DELAY)

    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        template = f.read()

    data_json = json.dumps(events, ensure_ascii=False).replace("</", r"<\/")
    out = template.replace("__DATA__", data_json).replace("__SUB__", build_sub(sat, sun, len(events)))

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)
    print("{}개 행사로 {} 갱신 완료".format(len(events), OUT_FILE))


if __name__ == "__main__":
    main()
