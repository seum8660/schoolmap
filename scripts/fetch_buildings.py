# -*- coding: utf-8 -*-
"""
학교별 건축물대장(표제부) 수집 → data/buildings.json
- 학교 지번주소에서 미리 계산한 시군구·법정동·본번·부번(scripts/schools_base.json)으로 직접 조회합니다.
- 인증키: BLDG_KEY (깃허브 Secrets). 결과 파일에는 키가 들어가지 않습니다.
- 출처: 국토교통부 건축HUB 건축물대장정보 서비스
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BK = os.environ.get("BLDG_KEY", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "buildings.json")
LIMIT = int(os.environ.get("LIMIT") or 0)
EPS = ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo",
       "https://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"]
EP = [None]
LAST_CNT = ["?"]
RECAP = ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrRecapTitleInfo",
         "https://apis.data.go.kr/1613000/BldRgstService_v2/getBrRecapTitleInfo"]
SKIP = ("공동주택", "단독주택", "근린생활", "업무시설", "창고")
if not BK: sys.exit("BLDG_KEY 환경변수가 없습니다.")

def call(q, ep_list=None):
    key = BK if "%" in BK else urllib.parse.quote(BK, safe="")
    last = ""
    for ep in (ep_list or ([EP[0]] if EP[0] else EPS)):
        url = ep + "?serviceKey=" + key + "&" + urllib.parse.urlencode(q)
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read().decode("utf-8"))
                h = (d.get("response") or {}).get("header") or {}
                if str(h.get("resultCode", "00")) in ("00", "0"):
                    if not ep_list: EP[0] = ep
                    LAST_CNT[0] = ((d.get("response") or {}).get("body") or {}).get("totalCount", "?")
                    items = ((d.get("response") or {}).get("body") or {}).get("items") or {}
                    items = items.get("item", []) if isinstance(items, dict) else []
                    return [items] if isinstance(items, dict) else items
                last = str(h.get("resultMsg", "")) + " / " + ep.split("/")[-2]
                break
            except Exception as e:
                last = str(e).replace(BK, "***") + " / " + ep.split("/")[-2]
                if i < 2: time.sleep(2 * (i + 1))
    raise RuntimeError(last)

def num(v):
    try: return float(str(v).replace(",", ""))
    except Exception: return 0.0

schools = json.load(open(os.path.join(HERE, "schools_base.json"), encoding="utf-8"))
PNU = {}
pf = os.path.join(HERE, "school_pnu.json")
if os.path.exists(pf):
    try:
        PNU = {k: v.get("pnu", []) for k, v in (json.load(open(pf, encoding="utf-8")).get("schools") or {}).items()}
        print(f"학교 지번(PNU) 자료 {len(PNU)}개교 사용")
    except Exception as e:
        print("school_pnu.json 읽기 실패: %s" % e, file=sys.stderr)

def q_from_pnu(pnu):
    return {"sigunguCd": pnu[0:5], "bjdongCd": pnu[5:10], "platGbCd": "1" if pnu[10] == "2" else "0",
            "bun": pnu[11:15], "ji": pnu[15:19], "numOfRows": "200", "pageNo": "1", "_type": "json"}
if LIMIT: schools = schools[:LIMIT]
res, fail, got, zero = {}, 0, 0, 0
for i, s in enumerate(schools, 1):
    try:
        items, how = [], ""
        for pnu in PNU.get(s["code"], []):
            got_items = call(q_from_pnu(pnu))
            if got_items: items += got_items; how = "PNU"
        base = {"sigunguCd": s["sigungu"], "bjdongCd": s["bjdong"], "platGbCd": s.get("plat", "0"),
                "bun": s["bun"], "ji": s["ji"], "numOfRows": "200", "pageNo": "1", "_type": "json"}
        if not items:
            items = call(base); how = "표제부"
        if not items and base["ji"] != "0000":                 # 부번 없이 재조회
            q2 = dict(base); q2["ji"] = "0000"; items = call(q2); how = "표제부(부번생략)"
        if not items and base["platGbCd"] == "0":                   # 산 지번으로 재조회
            q3 = dict(base); q3["platGbCd"] = "1"; items = call(q3); how = "표제부(산)"
        if not items:                                           # 총괄표제부
            items = call(base, RECAP); how = "총괄표제부"
        if not items:
            zero += 1
            if zero <= 3: print(f"  ? {s['n']}({s['addr']}) 건물 0건 · totalCount={LAST_CNT[0]}", file=sys.stderr)
        rows = []
        for it in items:
            ymd = str(it.get("useAprDay") or "").strip()
            u = (it.get("mainPurpsCdNm") or "").strip()
            if any(k in u for k in SKIP): continue
            rows.append({"n": (it.get("dongNm") or it.get("bldNm") or "").strip() or "건물",
                         "d": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) >= 8 else "",
                         "y": int(ymd[:4]) if ymd[:4].isdigit() else 0,
                         "a": round(num(it.get("totArea"))), "fl": int(num(it.get("grndFlrCnt"))),
                         "u": u, "s": (it.get("strctCdNm") or "").replace("구조", "").strip(),
                         "eq": (it.get("rserthqkDsgnApplyYn") or "").strip()})
        res[s["code"]] = {"n": s["n"], "addr": s["addr"], "how": how, "b": rows}
        if rows: got += 1
    except Exception as e:
        fail += 1
        print(f"  ! {s['n']}({s['addr']}): {e}", file=sys.stderr)
        if fail >= 5 and fail == i: sys.exit("첫 %d개교 모두 실패 — 위 '!' 줄의 문구를 확인하십시오." % i)
    if i % 50 == 0: print(f"  {i}/{len(schools)} 처리 · 건물 확인 {got}개교")
    time.sleep(0.12)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
json.dump({"updated": kst, "source": "국토교통부 건축HUB 건축물대장(표제부)", "schools": res},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"완료: {len(res)}개교 조회 · 건물 확인 {got}개교 · 0건 {zero}개교 · 실패 {fail}개교 → data/buildings.json")
