"""
Builds the report data for every company in companies.json.

Steps for each company:
  1. Ask the public ESEF archive (filings.xbrl.org) for the company's annual filings.
  2. Download each filing in xBRL-JSON format (the figures, tagged with IFRS codes).
  3. Map the IFRS codes to a standard set of lines (mapping.py).
  4. Calculate ratios, trends and the working-capital and cash views (metrics in this file).
  5. Write the key messages and points to watch with fixed rules (rules.py). No AI.
  6. Save data/<TICKER>.json for the app, plus data/companies.json (the search list).

Run:  python pipeline/build.py            (all companies, from the internet)
      python pipeline/build.py --offline  (use files already in pipeline/cache/)
"""
import json
import os
import sys
import datetime as dt
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from mapping import extract_year_values, standardise  # noqa: E402
from rules import build_messages  # noqa: E402

BASE = "https://filings.xbrl.org"
CACHE = os.path.join(HERE, "cache")
DATA = os.path.join(ROOT, "data")
YEARS_WANTED = 5
UA = {"User-Agent": "balances-report-builder/1.0 (+https://github.com/Tydra-HQ)"}


# ---------------------------------------------------------------- download

def http_json(url, tries=3):
    import requests
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:  # network hiccup: wait and retry
            if i == tries - 1:
                raise
            print(f"   retry {url}: {e}")
            time.sleep(5 * (i + 1))


def list_filings(company):
    """Annual ESEF filings of the company, newest first, one per fiscal year end."""
    lei = company["lei"]
    doc = http_json(f"{BASE}/api/entities/{lei}/filings?page[size]=200")
    if not doc or not doc.get("data"):
        # LEI not found: look the company up by name
        flt = json.dumps([{"name": "name", "op": "ilike", "val": f"%{company['search']}%"}])
        ents = http_json(f"{BASE}/api/entities?filter={flt}") or {}
        for ent in ents.get("data", []):
            lei = ent["attributes"]["identifier"]
            doc = http_json(f"{BASE}/api/entities/{lei}/filings?page[size]=200")
            if doc and doc.get("data"):
                company["lei"] = lei
                break
    rows = []
    for f in (doc or {}).get("data", []):
        a = f["attributes"]
        if not a.get("json_url") or not a.get("period_end"):
            continue
        rows.append({
            "id": f["id"], "period_end": a["period_end"], "json_url": a["json_url"],
            "report_url": a.get("report_url"), "processed": a.get("processed") or "",
            "errors": a.get("error_count") or 0,
        })
    # one filing per period end: fewest validation errors, then most recently processed
    best = {}
    for r in rows:
        k = r["period_end"]
        cur = best.get(k)
        if cur is None or (r["errors"], -_ts(r["processed"])) < (cur["errors"], -_ts(cur["processed"])):
            best[k] = r
    out = sorted(best.values(), key=lambda r: r["period_end"], reverse=True)
    return out[:YEARS_WANTED]


def _ts(s):
    try:
        return dt.datetime.fromisoformat(s[:19]).timestamp()
    except Exception:
        return 0


def load_filing(company, filing, offline):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{company['ticker']}_{filing['period_end']}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    if offline:
        return None
    print(f"   downloading {filing['period_end']} ...")
    doc = http_json(BASE + filing["json_url"])
    if doc is not None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
    return doc


# ---------------------------------------------------------------- metrics

def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def growth(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur / prev - 1) * 100 if prev > 0 else None


def compute_metrics(L, n):
    """L = dict of standard line -> list of values (oldest -> newest), € million."""
    def col(k):
        return L.get(k) or [None] * n

    rev, gp, ebitda, ebit, net = col("revenue"), col("gross_profit"), col("ebitda"), col("ebit"), col("net")
    m = {
        "gross_margin": [safe_div(g, r) * 100 if safe_div(g, r) is not None else None for g, r in zip(gp, rev)],
        "ebitda_margin": [safe_div(e, r) * 100 if safe_div(e, r) is not None else None for e, r in zip(ebitda, rev)],
        "ebit_margin": [safe_div(e, r) * 100 if safe_div(e, r) is not None else None for e, r in zip(ebit, rev)],
        "net_margin": [safe_div(e, r) * 100 if safe_div(e, r) is not None else None for e, r in zip(net, rev)],
    }
    inv, rec, pay, cos = col("inventories"), col("receivables"), col("payables"), col("cost_of_sales")
    m["owc"] = [None if None in (i, r, p) else i + r - p for i, r, p in zip(inv, rec, pay)]
    # days: inventory and payables on cost of sales when the company reports it, else on revenue
    basis = [c if c else r for c, r in zip(cos, rev)]
    m["days_basis"] = "cost_of_sales" if any(cos) else "revenue"
    m["days_inv"] = [safe_div(i, b) * 365 if safe_div(i, b) is not None else None for i, b in zip(inv, basis)]
    m["days_rec"] = [safe_div(r, v) * 365 if safe_div(r, v) is not None else None for r, v in zip(rec, rev)]
    m["days_pay"] = [safe_div(p, b) * 365 if safe_div(p, b) is not None else None for p, b in zip(pay, basis)]
    ocf, capex, leases = col("ocf"), col("capex"), col("lease_payments")
    m["fcf"] = [None if o is None or c is None else o - c - (l or 0) for o, c, l in zip(ocf, capex, leases)]
    cash, sti, debt = col("cash"), col("st_investments"), col("borrowings")
    m["net_cash"] = [None if c is None or d is None else c + (s or 0) - d for c, s, d in zip(cash, sti, debt)]
    m["net_debt_ebitda"] = [None if nc is None or not e or e <= 0 else -nc / e for nc, e in zip(m["net_cash"], ebitda)]
    eq = col("equity_parent")
    roe = [None] * n
    for i in range(n):
        if net[i] is None or eq[i] is None:
            continue
        avg = (eq[i] + eq[i - 1]) / 2 if i > 0 and eq[i - 1] is not None else eq[i]
        roe[i] = net[i] / avg * 100 if avg and avg > 0 else None
    m["roe"] = roe
    m["equity_ratio"] = [safe_div(e, a) * 100 if safe_div(e, a) is not None else None for e, a in zip(col("equity"), col("assets"))]
    m["growth"] = {k: [None] + [growth(L[k][i], L[k][i - 1]) for i in range(1, n)] for k in L if L[k]}
    return m


def fy_label(end):
    d = dt.date.fromisoformat(end)
    year = d.year if d.month >= 6 else d.year - 1
    return f"FY{year}"


# ---------------------------------------------------------------- main

def build_company(company, offline=False):
    print(f"== {company['ticker']} {company['name']}")
    filings = list_filings(company) if not offline else _cached_filings(company)
    if not filings:
        raise RuntimeError("no filings found")
    per_year = {}       # period_end -> {concept: value}
    currency = "EUR"
    sources = []
    # oldest first, so values from newer filings (restated prior years) win
    for f in sorted(filings, key=lambda r: r["period_end"]):
        doc = load_filing(company, f, offline)
        if not doc:
            continue
        vals, cur = extract_year_values(doc)
        currency = cur or currency
        for end, concepts in vals.items():
            per_year.setdefault(end, {}).update(concepts)
        sources.append({"fy": fy_label(f["period_end"]), "period_end": f["period_end"],
                        "url": BASE + f["report_url"] if f.get("report_url") else None})
    # keep fiscal years that have a full-year income statement (not just an opening balance)
    ends = sorted(e for e in per_year if per_year[e].get("_full_year"))
    ends = ends[-YEARS_WANTED:]
    if len(ends) < 2:
        raise RuntimeError("fewer than two years of data")
    lines = standardise([per_year[e] for e in ends])
    n = len(ends)
    metrics = compute_metrics(lines, n)
    years = [fy_label(e) for e in ends]
    data = {
        "ticker": company["ticker"], "name": company["name"], "legal": company["legal"],
        "lei": company["lei"], "sector": company["sector"], "currency": currency, "unit": "million",
        "years": years, "period_ends": ends,
        "lines": {k: [None if v is None else round(v, 3) for v in vals] for k, vals in lines.items()},
        "metrics": _round(metrics),
        "sources": sorted(sources, key=lambda s: s["period_end"], reverse=True),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    data["messages"] = build_messages(data)
    return data


def _round(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, list):
        return [_round(v) for v in x]
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    return x


def _cached_filings(company):
    if not os.path.isdir(CACHE):
        return []
    out = []
    for fn in os.listdir(CACHE):
        if fn.startswith(company["ticker"] + "_") and fn.endswith(".json"):
            pe = fn[len(company["ticker"]) + 1:-5]
            out.append({"period_end": pe, "json_url": None, "report_url": None, "processed": "", "errors": 0})
    return sorted(out, key=lambda r: r["period_end"], reverse=True)[:YEARS_WANTED]


def main():
    offline = "--offline" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    with open(os.path.join(HERE, "companies.json"), encoding="utf-8") as fh:
        companies = json.load(fh)
    os.makedirs(DATA, exist_ok=True)
    index_path = os.path.join(DATA, "companies.json")
    index = {c["ticker"]: c for c in (json.load(open(index_path, encoding="utf-8")) if os.path.exists(index_path) else [])}
    failures = 0
    for c in companies:
        if only and c["ticker"] not in only:
            continue
        entry = {"ticker": c["ticker"], "name": c["name"], "legal": c["legal"], "sector": c["sector"]}
        try:
            data = build_company(c, offline)
            with open(os.path.join(DATA, f"{c['ticker']}.json"), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            rev = data["lines"].get("revenue") or [None]
            entry.update({"available": True, "latest": data["years"][-1], "revenue": rev[-1],
                          "currency": data["currency"], "updated": data["generated_at"]})
            print(f"   ok: {', '.join(data['years'])}")
        except Exception as e:  # keep the last good data for this company
            failures += 1
            print(f"   FAILED: {e}")
            prev = index.get(c["ticker"], {})
            entry.update({k: prev[k] for k in ("available", "latest", "revenue", "currency", "updated") if k in prev})
            entry.setdefault("available", os.path.exists(os.path.join(DATA, f"{c['ticker']}.json")))
        index[c["ticker"]] = entry
    order = [c["ticker"] for c in companies]
    out = [index[t] for t in order if t in index]
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"done, {failures} failure(s)")


if __name__ == "__main__":
    main()
