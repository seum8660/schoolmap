# -*- coding: utf-8 -*-
"""
학교별 건축물 현황 수집 → data/buildings.json
1) 브이월드 연속지적도: 학교 좌표가 속한 필지 + 주변 학교용지(지목 '학') 필지의 PNU
2) 건축HUB 건축물대장 표제부: PNU별 동 목록(사용승인일·연면적·구조·층수·주용도·내진설계)
- 인증키: VWORLD_KEY, BLDG_KEY (깃허브 Secrets) — 결과 파일에는 키가 들어가지 않습니다.
- 출처: 국토교통부 건축HUB 건축물대장, 브이월드 연속지적도
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

VW = os.environ.get("VWORLD_KEY", "").strip()
BK = os.environ.get("BLDG_KEY", "").strip()
DOMAIN = os.environ.get("VW_DOMAIN") or "https://seum8660.github.io"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "buildings.json")
LIMIT = int(os.environ.get("LIMIT") or 0)          # 시험용: 앞에서부터 N개교만
if not VW or not BK: sys.exit("VWORLD_KEY 또는 BLDG_KEY 환경변수가 없습니다.")

def get(url, tries=3, tag=""):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": DOMAIN + "/"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                raise RuntimeError(tag + str(e).replace(VW, "***").replace(BK, "***"))
            time.sleep(1.5 * (i + 1))

def vw_parcels(x, y):
    """학교 좌표 필지 + 반경 약 150m 안 학교용지 필지"""
    base = "https://api.vworld.kr/req/data?service=data&version=2.0&request=GetFeature&data=LP_PA_CBND_BUBUN&format=json&geometry=false&crs=EPSG:4326&size=100"
    auth = "&key=" + urllib.parse.quote(VW) + "&domain=" + urllib.parse.quote(DOMAIN)
    out = {}
    d = get(base + auth + "&geomFilter=" + urllib.parse.quote(f"POINT({x} {y})"), tag="[브이월드 지적] ")
    r = d.get("response", {})
    if r.get("status") == "ERROR": raise RuntimeError("브이월드: " + str(r.get("error", {}).get("text", "")))
    for f in (r.get("result", {}).get("featureCollection", {}).get("features") or []):
        p = f.get("properties", {}); out[p.get("pnu")] = p.get("jibun", "")
    b = f"BOX({x-0.0016},{y-0.0013},{x+0.0016},{y+0.0013})"
    d = get(base + auth + "&geomFilter=" + urllib.parse.quote(b) + "&attrFilter=" + urllib.parse.quote("jibun:like:학"), tag="[브이월드 지적] ")
    for f in (d.get("response", {}).get("result", {}).get("featureCollection", {}).get("features") or []):
        p = f.get("properties", {})
        if str(p.get("jibun", "")).strip().endswith("학"): out[p.get("pnu")] = p.get("jibun", "")
    return {k: v for k, v in out.items() if k and len(k) == 19}

BLD_EPS = ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo",
           "https://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"]
BLD_EP = [None]

def bldg(pnu):
    q = {"sigunguCd": pnu[0:5], "bjdongCd": pnu[5:10], "platGbCd": "1" if pnu[10] == "2" else "0",
         "bun": pnu[11:15], "ji": pnu[15:19], "numOfRows": "200", "pageNo": "1", "_type": "json"}
    key = BK if "%" in BK else urllib.parse.quote(BK, safe="")
    eps = [BLD_EP[0]] if BLD_EP[0] else BLD_EPS
    last = None
    for ep in eps:
        try:
            d = get(ep + "?serviceKey=" + key + "&" + urllib.parse.urlencode(q), tries=2, tag="[건축물대장] ")
            head0 = (d.get("response") or {}).get("header") or {}
            if str(head0.get("resultCode", "00")) in ("00", "0"):
                BLD_EP[0] = ep
                break
            last = str(head0.get("resultMsg", "")) + " (" + ep.split("/")[-2] + ")"
        except Exception as e:
            last = str(e) + " (" + ep.split("/")[-2] + ")"
        d = None
    if not d:
        raise RuntimeError("건축물대장: " + str(last))
    body = (d.get("response") or {}).get("body") or {}
    items = (body.get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else []
    return [items] if isinstance(items, dict) else items

def num(v):
    try: return float(str(v).replace(",", ""))
    except Exception: return 0.0

schools = json.load(open(os.path.join(HERE, "schools_base.json"), encoding="utf-8"))
if LIMIT: schools = schools[:LIMIT]
res, fail = {}, 0
for i, s in enumerate(schools, 1):
    try:
        pnus = vw_parcels(s["x"], s["y"])
        rows = []
        for pnu, jb in pnus.items():
            for it in bldg(pnu):
                ymd = str(it.get("useAprDay") or "").strip()
                rows.append({"n": (it.get("dongNm") or it.get("bldNm") or "").strip() or "건물",
                             "d": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) >= 8 else "",
                             "y": int(ymd[:4]) if ymd[:4].isdigit() else 0,
                             "a": round(num(it.get("totArea"))), "fl": int(num(it.get("grndFlrCnt"))),
                             "u": (it.get("mainPurpsCdNm") or "").strip(), "s": (it.get("strctCdNm") or "").replace("구조", "").strip(),
                             "eq": (it.get("rserthqkDsgnApplyYn") or "").strip(), "pnu": pnu, "jb": jb})
            time.sleep(0.12)
        # 학교와 무관한 대형 건물(아파트 등) 제외
        rows = [r for r in rows if not any(k in r["u"] for k in ("공동주택", "단독주택", "근린생활", "업무시설"))]
        res[s["code"]] = {"n": s["n"], "pnu": list(pnus.keys()), "b": rows}
    except Exception as e:
        fail += 1; print(f"  ! {s['n']}: {e}", file=sys.stderr)
        if fail == 1: print("  (첫 실패 상세는 위 '!' 줄의 [대괄호] 표시로 어느 서버인지 구분됩니다)", file=sys.stderr)
        if fail >= 5 and fail == i:
            sys.exit("첫 %d개교 모두 실패했습니다. 위 '!' 줄의 오류 문구를 확인하십시오." % i)
        if fail >= 40 and fail > i * 0.5: sys.exit("오류가 많아 중단합니다.")
    if i % 50 == 0: print(f"  {i}/{len(schools)} 처리")
    time.sleep(0.1)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
json.dump({"updated": kst, "source": "국토교통부 건축HUB 건축물대장(표제부) · 브이월드 연속지적도", "schools": res},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
got = sum(1 for v in res.values() if v["b"])
print(f"완료: {len(res)}개교 조회 · 건물 확인 {got}개교 · 실패 {fail}개교 → data/buildings.json")
