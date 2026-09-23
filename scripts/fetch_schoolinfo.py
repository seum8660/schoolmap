# -*- coding: utf-8 -*-
"""
학교알리미 Open API → data/schoolinfo.json (전남광주 시도코드 12)
- 인증키: 환경변수 SCHOOLINFO_KEY (깃허브 Secrets). 결과 파일에는 키가 들어가지 않습니다.
- 수집: 학교기본정보(apiType 0), 학년별·학급별 학생수(apiType 09)
- 학교알리미는 최근 3년 자료만 제공하므로, 최신 공시연도와 2년 전 공시연도 학생수를 함께 저장합니다.
- 출처: 교육부·한국교육학술정보원 학교알리미(공공누리 출처표시)
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://www.schoolinfo.go.kr/openApi.do"
KEY = os.environ.get("SCHOOLINFO_KEY", "").strip()
SIDO = os.environ.get("SI_SIDO") or "12"           # 전남광주통합특별시
SGG = SIDO + "000"
KINDS = {"02": "초", "03": "중", "04": "고"}
NOW = datetime.now().year
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "schoolinfo.json")

def call(item, kind, year):
    q = {"apiKey": KEY, "apiType": item, "pbanYr": year, "schulKndCode": kind, "sidoCode": SIDO, "sggCode": SGG}
    url = BASE + "?" + urllib.parse.urlencode(q)
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("resultCode") == "success":
                return d.get("list") or []
            msg = str(d.get("resultMsg", ""))
            if "공시되지 않은" in msg or "존재하지" in msg:
                return None
            raise RuntimeError(msg)
        except Exception as e:
            if i == 2:
                print(f"  ! apiType={item} 학교급={kind} {year}년: {str(e).replace(KEY, '***')}", file=sys.stderr)
                return []
            time.sleep(2 * (i + 1))

def num(v):
    try: return int(float(str(v).replace(",", "")))
    except Exception: return None

def latest(item, kind):
    for y in (NOW, NOW - 1, NOW - 2):
        rows = call(item, kind, y)
        if rows: return y, rows
    return None, []

if not KEY:
    sys.exit("SCHOOLINFO_KEY 환경변수가 없습니다.")

S = {}
years = {}
for kind, kn in KINDS.items():
    y0, base = latest("0", kind)
    for r in base:
        c = r.get("SCHUL_CODE")
        if not c: continue
        S.setdefault(c, {"code": c, "name": r.get("SCHUL_NM"), "kind": kn})
        S[c].update({"addr": r.get("SCHUL_RDNMA") or r.get("ADRES_BRKDN"), "lat": r.get("LTTUD"), "lng": r.get("LGTUD")})
    y, rows = latest("09", kind)
    if y:
        years[kn] = y
        for r in rows:
            c = r.get("SCHUL_CODE")
            if not c: continue
            o = S.setdefault(c, {"code": c, "name": r.get("SCHUL_NM"), "kind": kn})
            o.update({"st": num(r.get("COL_S_SUM")), "cl": num(r.get("COL_C_SUM")), "year": y})
        prev = call("09", kind, y - 2) or []
        for r in prev:
            c = r.get("SCHUL_CODE")
            if c in S: S[c]["st_prev"] = num(r.get("COL_S_SUM")); S[c]["prev_year"] = y - 2
    print(f"[{kn}] 기본정보 {len(base)}건 · 학생수 {len(rows)}건 ({y or '-'}년)")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
json.dump({"updated": kst, "sido": SIDO, "years": years, "source": "학교알리미 Open API", "schools": list(S.values())},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print(f"완료: {len(S)}개교 → data/schoolinfo.json")
