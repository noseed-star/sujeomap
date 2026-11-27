"""수저맵 한국 데이터 만들기

착한가격업소 CSV(data/raw/*.csv)를 읽어
 1) 식당 업종 + 3만 원 이하 메뉴가 있는 가게만 고르고
 2) 도로명주소 검색 API로 주소 코드(행정구역코드·도로명코드·건물번호)를 찾고
 3) 좌표제공 검색 API로 좌표를 받아 위경도로 바꾼 뒤
 4) data/kr.json 으로 저장합니다.

- 한 번 찾은 주소는 data/cache/geocode.json 에 저장해서 다음 실행 때 다시 부르지 않아요.
- JUSO_COORD_KEY 가 없으면 2)까지만 하고 끝내요. (좌표 키 발급 전에도 미리 돌려둘 수 있어요)
- SIDO 환경변수로 이번에 처리할 시도를 고를 수 있어요. (예: 서울특별시 / 전국)

착한가격업소 데이터는 공공데이터포털 오픈 API에서 가장 최근 버전을 자동으로 가져와요.
(DATA_GO_KR_KEY 가 없을 때만 예전처럼 data/raw/*.csv 를 읽어요)

필요한 환경변수: DATA_GO_KR_KEY, JUSO_SEARCH_KEY, (선택) JUSO_COORD_KEY, (선택) SIDO, (선택) LIMIT
"""
import csv
import glob
import io
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from pyproj import Transformer

RAW_GLOB = "data/raw/*.csv"
OUT_PATH = "data/kr.json"
REPORT_PATH = "data/kr_report.json"
CACHE_PATH = "data/cache/geocode.json"

SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
COORD_URL = "https://business.juso.go.kr/addrlink/addrCoordApi.do"

MAX_PRICE = 30000            # 수저맵 검색 최대 금액
FOOD_TYPES = {"한식", "중식", "일식", "양식", "기타요식업"}
MENU_ALIAS = {"자장면": "짜장면", "쟁반자장": "쟁반짜장", "간짜장면": "간짜장"}
SLEEP = 0.12                 # 호출 간격(초) - 너무 빠르면 E0007
KST = timezone(timedelta(hours=9))

DATA_KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
GOOD_PRICE_NS = "3045247/v1"   # 공공데이터포털 '행정안전부_착한가격업소 현황' 오픈 API
SEARCH_KEY = os.environ.get("JUSO_SEARCH_KEY", "").strip()
COORD_KEY = os.environ.get("JUSO_COORD_KEY", "").strip()
SIDO = os.environ.get("SIDO", "서울특별시").strip() or "서울특별시"
LIMIT = int(os.environ.get("LIMIT", "0") or 0)

to_wgs84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
session = requests.Session()
session.headers["User-Agent"] = "sujeomap-data-builder"


# ---------- CSV ----------
def read_csv():
    files = sorted(glob.glob(RAW_GLOB))
    if not files:
        sys.exit("data/raw 폴더에 착한가격업소 CSV가 없어요. 공공데이터포털에서 받아 올려 주세요.")
    path = files[-1]
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"{path} 인코딩을 읽지 못했어요.")
    m = re.search(r"(20\d{6})", os.path.basename(path))
    base = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else os.environ.get("BASE_DATE", "")
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"CSV: {os.path.basename(path)} · {len(rows):,}행 · 기준일 {base or '알 수 없음'}")
    return rows, base, os.path.basename(path)


def read_api():
    """착한가격업소 오픈 API: 새 파일이 올라올 때마다 호출 주소(uddi)가 바뀌어서, 목록에서 가장 최근 것을 골라요."""
    spec = requests.get("https://infuser.odcloud.kr/oas/docs", params={"namespace": GOOD_PRICE_NS}, timeout=30).json()
    best = None
    for path, v in spec.get("paths", {}).items():
        summary = v.get("get", {}).get("summary", "")
        m = re.search(r"(20\d{6})", summary)
        if m and (best is None or m.group(1) > best[1]):
            best = (path, m.group(1), summary)
    if not best:
        sys.exit("착한가격업소 API 목록을 읽지 못했어요.")
    path, ymd, summary = best
    url = "https://api.odcloud.kr/api" + path
    rows, page = [], 1
    while True:
        r = requests.get(url, params={"serviceKey": DATA_KEY, "page": page, "perPage": 1000, "returnType": "JSON"}, timeout=60)
        if r.status_code in (401, 403):
            sys.exit("공공데이터포털 인증키가 맞지 않거나, '행정안전부_착한가격업소 현황' 오픈 API 활용신청이 아직 안 됐어요.\n" + r.text[:200])
        r.raise_for_status()
        j = r.json()
        data = j.get("data") or []
        rows.extend(data)
        if not data or len(rows) >= int(j.get("totalCount") or 0):
            break
        page += 1
        time.sleep(0.2)
    base = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    print(f"API: {summary} · {len(rows):,}행 · 기준일 {base}", flush=True)
    return rows, base, summary


def to_price(v):
    d = re.sub(r"[^0-9]", "", v or "")
    return int(d) if d else 0


def clean_menu(name):
    n = re.sub(r"\s+", " ", (name or "").strip())
    return MENU_ALIAS.get(n, n)


def addr_key(addr):
    """검색에 쓸 주소: 도로명 + 건물번호까지만 (층·호·괄호 제거)"""
    a = re.sub(r"\s+", " ", (addr or "").strip())
    a = re.sub(r"\(.*?\)", " ", a).strip()
    m = re.match(r"^(.+?(?:로|길)\s*\d+(?:-\d+)?)(?=\s|,|$)", a)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return a.split(",")[0].strip()[:60]


def shops_from_rows(rows):
    shops = []
    for i, r in enumerate(rows):
        r = {k.strip().lstrip("﻿"): ("" if v is None else str(v)).strip() for k, v in r.items() if k}
        if r.get("업종") not in FOOD_TYPES or not r.get("업소명") or not r.get("주소"):
            continue
        menus = []
        for k in range(1, 5):
            name, price = clean_menu(r.get(f"메뉴{k}")), to_price(r.get(f"가격{k}"))
            if name and price > 0:
                menus.append([name, price])
        if not menus or min(p for _, p in menus) > MAX_PRICE:
            continue
        shops.append({
            "id": f"kr{i}",
            "name": r["업소명"], "cat": r["업종"],
            "sido": r.get("시도", ""), "sgg": r.get("시군", ""),
            "addr": r["주소"], "key": addr_key(r["주소"]), "menus": menus,
        })
    return shops


# ---------- juso API ----------
class Blocked(Exception):
    pass


def _alarm(signum, frame):
    raise TimeoutError("응답이 25초 넘게 없어요")


signal.signal(signal.SIGALRM, _alarm)


def call(url, params, tries=4):
    for t in range(tries):
        try:
            signal.alarm(25)          # 한 번 호출이 25초를 넘으면 끊기 (응답을 질질 끄는 경우 대비)
            try:
                res = session.get(url, params=params, timeout=(6, 12))
                res.raise_for_status()
                data = res.json()["results"]
            finally:
                signal.alarm(0)
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as e:
            if t == tries - 1:
                raise Blocked(str(e))
            time.sleep(3 * (t + 1))
            continue
        code = data["common"]["errorCode"]
        if code == "E0007":                # 너무 빠른 호출
            time.sleep(5 * (t + 1))
            continue
        return code, data["common"]["errorMessage"], data.get("juso") or []
    return "E0007", "호출 제한", []


def search(keyword):
    code, msg, juso = call(SEARCH_URL, {"confmKey": SEARCH_KEY, "currentPage": 1, "countPerPage": 5,
                                        "keyword": keyword, "resultType": "json"})
    if code != "0":
        return None, f"{code} {msg}"
    if not juso:
        return None, "검색 결과 없음"
    j = juso[0]
    return {"admCd": j["admCd"], "rnMgtSn": j["rnMgtSn"], "udrtYn": j["udrtYn"],
            "buldMnnm": j["buldMnnm"], "buldSlno": j["buldSlno"], "roadAddr": j.get("roadAddrPart1", "")}, None


def coord(codes):
    params = {k: codes[k] for k in ("admCd", "rnMgtSn", "udrtYn", "buldMnnm", "buldSlno")}
    params.update({"confmKey": COORD_KEY, "resultType": "json"})
    code, msg, juso = call(COORD_URL, params)
    if code != "0":
        return None, f"{code} {msg}"
    if not juso or not juso[0].get("entX"):
        return None, "좌표 없음"
    lng, lat = to_wgs84.transform(float(juso[0]["entX"]), float(juso[0]["entY"]))
    return (round(lat, 6), round(lng, 6)), None


def preflight():
    """해외 서버(GitHub Actions)에서 막히는지 먼저 한 번 확인"""
    print("도로명주소 API 연결 확인 중… (최대 1분)", flush=True)
    try:
        code, msg, _ = call(SEARCH_URL, {"confmKey": SEARCH_KEY, "currentPage": 1, "countPerPage": 1,
                                         "keyword": "세종대로 110", "resultType": "json"}, tries=2)
    except Blocked as e:
        sys.exit("도로명주소 API 서버에 연결하지 못했어요. 해외 서버 접속이 막혔을 수 있어요.\n"
                 "→ 같은 스크립트를 내 PC에서 실행해 주세요. (README 'PC에서 실행하기')\n" + str(e))
    if code != "0":
        sys.exit(f"도로명주소 검색 API 키 확인이 필요해요: {code} {msg}")
    print("도로명주소 검색 API 연결 OK")


# ---------- main ----------
def main():
    if not SEARCH_KEY:
        sys.exit("JUSO_SEARCH_KEY 가 없어요. 저장소 Settings → Secrets 에 등록해 주세요.")
    rows, base, fname = read_api() if DATA_KEY else read_csv()
    shops = shops_from_rows(rows)
    print(f"식당 + 3만 원 이하 메뉴 보유: {len(shops):,}곳")

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache = json.load(open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else {}

    targets = [s for s in shops if SIDO == "전국" or s["sido"] == SIDO]
    keys = []
    for s in targets:
        if s["key"] not in keys:
            keys.append(s["key"])
    print(f"이번 처리 범위: {SIDO} · 가게 {len(targets):,}곳 · 주소 {len(keys):,}개")
    if not COORD_KEY:
        print("JUSO_COORD_KEY 가 없어서 주소 코드 찾기까지만 할게요.")

    preflight()
    done = 0
    try:
        for k in keys:
            c = cache.get(k, {})
            changed = False
            if "codes" not in c:
                codes, err = search(k)
                c = {"codes": codes, "err": err}
                changed = True
                time.sleep(SLEEP)
            if COORD_KEY and c.get("codes") and "lat" not in c and not c.get("cerr"):
                ll, err = coord(c["codes"])
                if ll:
                    c["lat"], c["lng"] = ll
                else:
                    c["cerr"] = err
                changed = True
                time.sleep(SLEEP)
            if changed:
                cache[k] = c
                done += 1
                if done % 10 == 0:
                    print(f"  … {done:,}개 처리", flush=True)
                if done % 200 == 0:
                    json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
                if LIMIT and done >= LIMIT:
                    print(f"LIMIT {LIMIT}개에서 멈춰요.")
                    break
    except Blocked as e:
        print("중간에 연결이 끊겼어요. 지금까지 결과는 저장할게요.", e)
    finally:
        json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)

    # ---------- 출력 (CSV 전체 중 좌표가 있는 가게 모두) ----------
    out, fails = [], []
    for s in shops:
        c = cache.get(s["key"], {})
        if "lat" in c:
            out.append([s["id"], s["name"], s["cat"], s["sido"], s["sgg"], s["addr"], c["lat"], c["lng"], s["menus"]])
        elif s["key"] in cache and (SIDO == "전국" or s["sido"] == SIDO):
            fails.append({"name": s["name"], "addr": s["addr"], "why": c.get("err") or c.get("cerr") or "좌표 대기"})

    meta = {
        "source": "행정안전부 착한가격업소 현황 (공공데이터포털)",
        "file": fname, "base_date": base, "max_price": MAX_PRICE,
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "count": len(out),
    }
    json.dump({"meta": meta, "fields": ["id", "name", "cat", "sido", "sgg", "addr", "lat", "lng", "menus"], "shops": out},
              open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    by_sido = {}
    for s in out:
        by_sido[s[3]] = by_sido.get(s[3], 0) + 1
    coded = sum(1 for k in keys if cache.get(k, {}).get("codes"))
    report = {"meta": meta, "range": SIDO, "shops_in_range": len(targets), "addresses_in_range": len(keys),
              "address_codes_found": coded, "on_map_by_sido": by_sido, "coord_key": bool(COORD_KEY),
              "not_on_map_sample": fails[:100], "not_on_map_count": len(fails)}
    json.dump(report, open(REPORT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n===== 결과 =====")
    print(f"주소 코드 찾음: {coded:,} / {len(keys):,}")
    print(f"지도에 올라간 가게(전체): {len(out):,}곳 {by_sido}")
    print(f"이번 범위에서 아직 지도에 못 올린 가게: {len(fails):,}곳 (data/kr_report.json 참고)")


if __name__ == "__main__":
    main()
