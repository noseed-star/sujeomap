"""소상공인시장진흥공단 상가(상권)정보 → 수저맵 데이터

공공데이터포털 '소상공인시장진흥공단_상가(상권)정보' 오픈 API(storeListInDong)로
한 시도의 음식점(업종 대분류 I2)을 모두 받아서

 1) data/sbiz/<시도코드>/<시군구코드>.json  : 제보할 때 '가게 찾기'에 쓰는 음식점 목록
 2) data/sbiz/index.json                    : 시군구별 파일 목록과 범위(지도 위치로 파일 고르기용)
 3) data/chains.json                         : data/brands.csv 에 가격을 넣은 체인 브랜드 매장 (지도에 표시)

를 만듭니다. 상가정보에는 가격이 없어서 지도에는 체인 가격표와 맞는 매장만 올라가요.

필요한 환경변수: DATA_GO_KR_KEY (공공데이터포털 일반 인증키, Decoding), (선택) SIDO_CD (기본 11 = 서울)
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

API = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
SIDO_CD = os.environ.get("SIDO_CD", "11").strip() or "11"
ROWS = 1000
OUT_DIR = "data/sbiz"
BRANDS = "data/brands.csv"
CHAINS_OUT = "data/chains.json"
KST = timezone(timedelta(hours=9))
SIDO_NAME = {"11": "서울특별시", "26": "부산광역시", "27": "대구광역시", "28": "인천광역시", "29": "광주광역시",
             "30": "대전광역시", "31": "울산광역시", "36": "세종특별자치시", "41": "경기도", "43": "충청북도",
             "44": "충청남도", "46": "전라남도", "47": "경상북도", "48": "경상남도", "50": "제주특별자치도",
             "51": "강원특별자치도", "52": "전북특별자치도"}

# 상가정보 업종 중분류 → 수저맵 업종
def to_cat(mcls):
    m = mcls or ""
    if "한식" in m:
        return "한식"
    if "중식" in m:
        return "중식"
    if "일식" in m:
        return "일식"
    if "서양" in m or "양식" in m:
        return "양식"
    return "기타요식업"


def fetch_page(page, tries=4):
    params = {"serviceKey": KEY, "divId": "ctprvnCd", "key": SIDO_CD, "indsLclsCd": "I2",
              "numOfRows": ROWS, "pageNo": page, "type": "json"}
    for t in range(tries):
        try:
            r = requests.get(API, params=params, timeout=(8, 40))
            text = r.text
            if not text.strip().startswith("{"):
                # 키 오류 등은 XML로 와요
                msg = re.findall(r"<returnAuthMsg>(.*?)</returnAuthMsg>|<resultMsg>(.*?)</resultMsg>", text)
                raise RuntimeError(f"API 응답 오류: {msg or text[:200]}")
            j = r.json()
            code = j.get("header", {}).get("resultCode")
            if code == "03":                      # 데이터 없음
                return [], 0, j.get("header", {})
            if code not in ("00", None):
                raise RuntimeError(f"API 오류 {code}: {j.get('header', {}).get('resultMsg')}")
            body = j.get("body", {})
            return body.get("items") or [], int(body.get("totalCount") or 0), j.get("header", {})
        except (requests.ConnectionError, requests.Timeout) as e:
            if t == tries - 1:
                raise
            time.sleep(4 * (t + 1))
    return [], 0, {}


def main():
    if not KEY:
        sys.exit("DATA_GO_KR_KEY 가 없어요. 저장소 Settings → Secrets 에 공공데이터포털 인증키(Decoding)를 등록해 주세요.")
    print(f"상가정보 음식점 받기: {SIDO_NAME.get(SIDO_CD, SIDO_CD)} ({SIDO_CD})", flush=True)
    items, total, header = fetch_page(1)
    if not total:
        sys.exit("받은 데이터가 없어요. 시도코드나 활용신청 상태를 확인해 주세요.")
    pages = (total + ROWS - 1) // ROWS
    print(f"전체 {total:,}곳 · {pages}페이지", flush=True)
    for p in range(2, pages + 1):
        more, _, _ = fetch_page(p)
        items.extend(more)
        if p % 10 == 0:
            print(f"  … {p}/{pages}페이지", flush=True)
        time.sleep(0.2)
    stdr = header.get("stdrYm", "")

    # ---------- 시군구별 파일 ----------
    by_gu = {}
    for it in items:
        try:
            lng, lat = float(it.get("lon")), float(it.get("lat"))
        except (TypeError, ValueError):
            continue
        gu = it.get("signguCd") or "0"
        by_gu.setdefault(gu, {"nm": it.get("signguNm", ""), "rows": []})["rows"].append([
            it.get("bizesId", ""), it.get("bizesNm", ""), it.get("brchNm") or "", to_cat(it.get("indsMclsNm")),
            it.get("indsSclsNm") or "", it.get("rdnmAdr") or it.get("lnoAdr") or "", round(lng, 6), round(lat, 6)])

    os.makedirs(f"{OUT_DIR}/{SIDO_CD}", exist_ok=True)
    index_path = f"{OUT_DIR}/index.json"
    index = json.load(open(index_path, encoding="utf-8")) if os.path.exists(index_path) else {"files": []}
    index["files"] = [f for f in index["files"] if f["sido"] != SIDO_CD]
    for gu, g in sorted(by_gu.items()):
        rows = g["rows"]
        lngs, lats = [r[6] for r in rows], [r[7] for r in rows]
        path = f"{OUT_DIR}/{SIDO_CD}/{gu}.json"
        json.dump({"fields": ["id", "name", "branch", "cat", "type", "addr", "lng", "lat"], "stores": rows},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        index["files"].append({"sido": SIDO_CD, "gu": gu, "nm": g["nm"], "count": len(rows), "path": path,
                               "bbox": [min(lngs), min(lats), max(lngs), max(lats)]})
    index["meta"] = {"source": "소상공인시장진흥공단 상가(상권)정보", "stdr_ym": stdr,
                     "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}
    json.dump(index, open(index_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"시군구 파일 {len(by_gu)}개 저장", flush=True)

    # ---------- 체인 가격표 매칭 ----------
    brands = []
    if os.path.exists(BRANDS):
        for r in csv.DictReader(open(BRANDS, encoding="utf-8-sig")):
            if (r.get("active") or "").strip().upper() == "Y" and r.get("match") and r.get("price"):
                brands.append(r)
    by_brand = {}
    for b in brands:
        by_brand.setdefault(b["match"].strip(), {"brand": b["brand"].strip(), "cat": b.get("cat") or "기타요식업",
                                                  "menus": [], "src": b.get("source_url", ""), "checked": b.get("checked_at", "")})
        by_brand[b["match"].strip()]["menus"].append([b["menu"].strip(), int(re.sub(r"[^0-9]", "", b["price"]))])

    chains = json.load(open(CHAINS_OUT, encoding="utf-8")) if os.path.exists(CHAINS_OUT) else {"shops": []}
    chains["shops"] = [s for s in chains.get("shops", []) if not s[0].startswith(f"sb{SIDO_CD}_")]
    matched = 0
    sido_nm = SIDO_NAME.get(SIDO_CD, "")
    for gu, g in by_gu.items():
        for row in g["rows"]:
            name = re.sub(r"\s+", "", row[1])
            for m, b in by_brand.items():
                if name.startswith(re.sub(r"\s+", "", m)):
                    disp = f"{b['brand']} {row[2]}".strip() if row[2] else row[1]
                    chains["shops"].append([f"sb{SIDO_CD}_{row[0]}", disp, b["cat"], sido_nm, g["nm"], row[5],
                                            row[7], row[6], b["menus"], b["src"], b["checked"]])
                    matched += 1
                    break
    chains["fields"] = ["id", "name", "cat", "sido", "sgg", "addr", "lat", "lng", "menus", "source_url", "checked_at"]
    chains["meta"] = {"source": "소상공인시장진흥공단 상가(상권)정보 + 체인 가격표(data/brands.csv)", "stdr_ym": stdr,
                      "brands": len(by_brand), "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
                      "count": len(chains["shops"])}
    json.dump(chains, open(CHAINS_OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"체인 가격표 브랜드 {len(by_brand)}개 · 매칭된 매장 {matched:,}곳", flush=True)
    print("완료", flush=True)


if __name__ == "__main__":
    main()
