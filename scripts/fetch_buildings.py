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
if not BK and sys.stdin.isatty():          # 내 PC에서 실행할 때: 키를 화면에 표시하지 않고 입력받음
    import getpass
    BK = getpass.getpass("건축HUB 인증키(Encoding 또는 Decoding) 붙여넣기 후 Enter: ").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "buildings.json")
LIMIT = int(os.environ.get("LIMIT") or 0)
TMO = int(os.environ.get("TIMEOUT") or 20)
TIMEOUTS = [0]
EPS = ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo",
       "https://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo"]
EP = [None]
LAST_CNT = ["?"]
RECAP = ["https://apis.data.go.kr/1613000/BldRgstHubService/getBrRecapTitleInfo",
         "https://apis.data.go.kr/1613000/BldRgstService_v2/getBrRecapTitleInfo"]
# 2026년 전남광주통합특별시 출범으로 시군구 코드 앞자리가 바뀜(법정동·번지는 동일).
# 브이월드 정제주소(level4LC)로 시군별 확인: 2026-10-21
NEWSG = {"46110": "12110", "46130": "12130", "46150": "12150", "46170": "12170", "46230": "12190",
         "46710": "12710", "46720": "12720", "46730": "12730", "46770": "12740", "46780": "12750",
         "46790": "12760", "46800": "12770", "46810": "12780", "46820": "12790", "46830": "12800",
         "46840": "12810", "46860": "12820", "46870": "12830", "46880": "12840", "46890": "12850",
         "46900": "12860", "46910": "12870"}
OLDSG = {v: k for k, v in NEWSG.items()}
def sg_try(sg):
    """새 코드 먼저, 결과가 없으면 옛 코드로 조회"""
    n = NEWSG.get(sg, sg); o = OLDSG.get(n, sg)
    return [n] if n == o else [n, o]
SKIP = ("공동주택", "단독주택", "근린생활", "업무시설", "창고")
if not BK: sys.exit("BLDG_KEY 환경변수가 없습니다.")

def call(q, ep_list=None):
    key = BK if "%" in BK else urllib.parse.quote(BK, safe="")
    last = ""
    for ep in (ep_list or ([EP[0]] if EP[0] else EPS)):
        url = ep + "?serviceKey=" + key + "&" + urllib.parse.urlencode(q)
        for i in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=TMO) as r:
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
                if "timed out" in last:
                    TIMEOUTS[0] += 1
                    if TIMEOUTS[0] >= 4 and EP[0] is None:
                        raise RuntimeError("공공데이터포털 응답 없음(시간초과)")
                    break
                if i < 4: time.sleep(3 * (i + 1))
    raise RuntimeError(last)

def call_sg(q, ep_list=None):
    for sg in sg_try(q["sigunguCd"]):
        q2 = dict(q); q2["sigunguCd"] = sg
        items = call(q2, ep_list)
        if items: return items
    return []

import re
def stem(n):
    """학교명 끝 3글자(예: 완도신지중학교→신지중, 무안사랑초등학교→사랑초)"""
    t = re.sub(r"\s|\(.*?\)", "", n or "").replace("등학교", "").replace("학교", "")
    return t[-3:] if len(t) >= 3 else t
def nrm(t):
    return re.sub(r"\s|\(.*?\)", "", t or "").replace("등학교", "").replace("학교", "")
OTHERS = None
def mine(it, st, my_n):
    """건물명에 '목록에 있는 다른 학교' 이름이 들어 있을 때만 제외(학교법인·옛 교명은 그대로 둠)"""
    bn = nrm(it.get("bldNm"))
    if not bn: return True
    if st in bn: return True
    me = nrm(my_n)
    for o in OTHERS:
        if o != me and len(o) >= 3 and o in bn and o not in me: return False
    return True
def by_dong(s, st):
    """본번 지번에서 0건일 때: 같은 법정동 전체 대장에서 학교명이 들어간 교육연구시설만 골라냄"""
    out = []
    for sg in sg_try(s["sigungu"]):
        for pg in range(1, 11):
            items = call({"sigunguCd": sg, "bjdongCd": s["bjdong"], "numOfRows": "100", "pageNo": str(pg), "_type": "json"})
            out += [it for it in items if "교육연구" in (it.get("mainPurpsCdNm") or "") and st in re.sub(r"\s", "", (it.get("bldNm") or "")).replace("등학교", "")]
            if len(items) < 100: break
        if out: return out
    return []

def num(v):
    try: return float(str(v).replace(",", ""))
    except Exception: return 0.0

schools = json.load(open(os.path.join(HERE, "schools_base.json"), encoding="utf-8"))
OTHERS = sorted({nrm(x["n"]) for x in schools}, key=len, reverse=True)
OTHERS = [o for o in OTHERS if len(o) >= 3]
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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
LOCK = threading.Lock()
kst_now = lambda: datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
# 이어받기: 이미 건물이 확인된 학교는 건너뜀(FULL=1이면 전부 다시)
res = {}
if not os.environ.get("FULL") and os.path.exists(OUT):
    try: res = {k: v for k, v in json.load(open(OUT, encoding="utf-8"))["schools"].items() if v.get("b")}
    except Exception: res = {}
todo = [s for s in schools if s["code"] not in res]
print(f"대상 {len(schools)}개교 · 이미 확인 {len(res)}개교 · 이번 조회 {len(todo)}개교")
def save(final=False):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated": kst_now(), "source": "국토교통부 건축HUB 건축물대장(표제부)", "schools": res},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
fail, got, zero, done = 0, 0, 0, 0
T0 = time.time(); MAXMIN = int(os.environ.get("MAXMIN") or 100)
def work(s):
    if time.time() - T0 > MAXMIN * 60: return s, None, "시간제한"
    try:
        items, how = [], ""
        for pnu in PNU.get(s["code"], []):
            got_items = call_sg(q_from_pnu(pnu))
            if got_items: items += got_items; how = "PNU"
        base = {"sigunguCd": s["sigungu"], "bjdongCd": s["bjdong"], "platGbCd": s.get("plat", "0"),
                "bun": s["bun"], "ji": s["ji"], "numOfRows": "200", "pageNo": "1", "_type": "json"}
        if not items:
            items = call_sg(base); how = "표제부"
        if not items and base["ji"] != "0000":                 # 부번 없이 재조회
            q2 = dict(base); q2["ji"] = "0000"; items = call_sg(q2); how = "표제부(부번생략)"
        if not items and base["platGbCd"] == "0":                   # 산 지번으로 재조회
            q3 = dict(base); q3["platGbCd"] = "1"; items = call_sg(q3); how = "표제부(산)"
        if not items:                                           # 같은 법정동에서 학교명으로 찾기
            items = by_dong(s, stem(s["n"])); how = "법정동 내 학교명 검색"
        rows, st, other = [], stem(s["n"]), 0
        for it in items:
            ymd = re.sub(r"\D", "", str(it.get("useAprDay") or ""))
            u = (it.get("mainPurpsCdNm") or "").strip()
            if any(k in u for k in SKIP): continue
            if not mine(it, st, s["n"]): other += 1; continue
            dn, bn, ep = [(it.get(k) or "").strip() for k in ("dongNm", "bldNm", "etcPurps")]
            nm = " ".join(x for x in (dn, bn if bn and bn != dn else "") if x) or "건물"
            if ep and ep not in nm and ep != u: nm += f"({ep})"
            rows.append({"n": nm,
                         "d": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) >= 8 else (ymd[:4] if len(ymd) >= 4 else ""),
                         "y": int(ymd[:4]) if ymd[:4].isdigit() else 0,
                         "a": round(num(it.get("totArea"))), "fl": int(num(it.get("grndFlrCnt"))),
                         "u": u, "s": (it.get("strctCdNm") or "").replace("구조", "").strip(),
                         "eq": (it.get("rserthqkDsgnApplyYn") or "").strip()})
        return s, {"n": s["n"], "addr": s["addr"], "how": how, "b": rows,
                   "nd": sum(1 for r in rows if not r["y"]), "ox": other}, ""
    except Exception as e:
        return s, None, str(e)
with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS") or 2)) as ex:
    futs = [ex.submit(work, s) for s in todo]
    for f in as_completed(futs):
        s, r, err = f.result(); done += 1
        with LOCK:
            if r is not None:
                res[s["code"]] = r
                if r["b"]: got += 1
                else:
                    zero += 1
                    if zero <= 15: print(f"  ? {s['n']}({s['addr']}) 건물 0건 · 조회코드 {'/'.join(sg_try(s['sigungu']))}", file=sys.stderr)
            elif err != "시간제한":
                fail += 1
                if fail <= 15: print(f"  ! {s['n']}({s['addr']}): {err}", file=sys.stderr)
            if done % 50 == 0:
                print(f"  {done}/{len(todo)} 처리 · 건물 확인 {got}개교 · {int(time.time()-T0)}초"); save()
            if done == 30 and got == 0 and fail >= 25:
                save(); sys.exit("처음 30개교 대부분 실패 — 위 '!' 줄의 문구를 확인하십시오.")

retry = [x for x in todo if x["code"] not in res]
if retry and time.time() - T0 < MAXMIN * 60:
    print(f"실패·미처리 {len(retry)}개교 재조회")
    for x in retry:
        x2, r, err = work(x)
        if r is not None:
            res[x["code"]] = r; fail -= 1 if fail else 0
            if r["b"]: got += 1
        time.sleep(0.5)
save(final=True)
total_ok = sum(1 for v in res.values() if v.get("b"))
print(f"완료: 이번 조회 {len(todo)}개교 · 건물 확인 {got}개교 · 0건 {zero}개교 · 실패 {fail}개교 → 누적 건물 확인 {total_ok}/{len(schools)}개교")
if total_ok < len(schools) - zero: print("남은 학교가 있으면 한 번 더 실행하면 이어서 조회합니다.")
