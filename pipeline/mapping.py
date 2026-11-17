"""
Reads an xBRL-JSON filing and maps IFRS codes to the app's standard lines.

This mapping table is where accounting judgement lives: each standard line
lists the IFRS concepts that can hold it, in order of preference. Companies
present their accounts differently (e.g. by function, with cost of sales,
or by nature, without it), so every line has fallbacks or stays empty.
All money amounts are converted to millions.
"""
import datetime as dt

BASE_KEYS = {"concept", "entity", "period", "unit", "language"}


def _date(s, is_end):
    """xBRL-JSON writes 'end of 31 Jan' as '2026-02-01T00:00:00'. Convert to 2026-01-31."""
    d = dt.date.fromisoformat(s[:10])
    if "T" in s and s[11:19] == "00:00:00" and is_end:
        d -= dt.timedelta(days=1)
    return d


def extract_year_values(doc):
    """Returns ({period_end_iso: {concept: value}}, currency). Only full-year
    durations (about 12 months) and balance-sheet instants, consolidated
    (facts without extra dimensions)."""
    out = {}
    currency = None
    for fact in (doc.get("facts") or {}).values():
        dims = fact.get("dimensions") or {}
        if set(dims) - BASE_KEYS:
            continue  # a breakdown (segment, component of equity...), not a total
        concept = dims.get("concept", "")
        unit = dims.get("unit") or ""
        raw = fact.get("value")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        name = concept.split(":", 1)[1] if concept.startswith("ifrs-full:") else concept
        if unit.startswith("iso4217:") and "/" not in unit:
            currency = currency or unit.split(":", 1)[1]
            val = val / 1e6
        elif name != "BasicEarningsLossPerShare":
            continue  # ratios, counts, per-share items other than EPS
        period = dims.get("period", "")
        if "/" in period:
            a, b = period.split("/")
            start, end = _date(a, False), _date(b, True)
            days = (end - start).days + 1
            if not 350 <= days <= 380:
                continue  # half-years, quarters, multi-year
            key = end.isoformat()
            bucket = out.setdefault(key, {})
            bucket["_full_year"] = True
        elif period:
            key = _date(period, True).isoformat()
            bucket = out.setdefault(key, {})
        else:
            continue
        bucket.setdefault(name, val)
    return out, currency


def _first(d, names, absolute=False):
    for n in names:
        if n in d and d[n] is not None:
            return abs(d[n]) if absolute else d[n]
    return None


def _sum(d, names, absolute=True):
    vals = [abs(d[n]) if absolute else d[n] for n in names if n in d and d[n] is not None]
    return sum(vals) if vals else None


def standardise(years, overrides=None):
    """years: list (oldest -> newest) of {concept: value}. Returns {line: [values]}.
    overrides: {line: [concepts]} for one company (its own extension codes, see
    companies.json "map"); the listed concepts are added up (absolute values).
    When none of them is present in a year, the generic rule applies."""
    L = {}
    overrides = overrides or {}

    def put(key, fn):
        names = overrides.get(key)
        vals = []
        for y in years:
            v = _sum(y, names) if names else None
            vals.append(v if v is not None else fn(y))
        L[key] = vals

    put("revenue", lambda y: _first(y, ["Revenue", "RevenueFromContractsWithCustomers", "RevenueAndOperatingIncome"])
        if any(k in y for k in ("Revenue", "RevenueFromContractsWithCustomers", "RevenueAndOperatingIncome"))
        else _sum(y, ["RevenueFromSaleOfGoods", "RevenueFromRenderingOfServices"]))
    put("cost_of_sales", lambda y: _first(y, ["CostOfSales"], True))
    put("gross_profit", lambda y: _first(y, ["GrossProfit"]) if "GrossProfit" in y else (
        y["Revenue"] - abs(y["CostOfSales"]) if "Revenue" in y and "CostOfSales" in y else None))
    put("opex", lambda y: _first(y, ["OperatingExpense"], True))
    put("da", lambda y: _first(y, [
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
        "AdjustmentsForDepreciationAndAmortisationExpense",
        "AdjustmentsForDepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
    ], True))
    put("ebit", lambda y: _first(y, ["ProfitLossFromOperatingActivities"]))
    L["ebitda"] = [None if e is None or d is None else e + d for e, d in zip(L["ebit"], L["da"])]
    put("finance", lambda y: _first(y, ["FinanceIncomeCost"]) if "FinanceIncomeCost" in y else (
        (y.get("FinanceIncome") or 0) - abs(y.get("FinanceCosts") or 0)
        if ("FinanceIncome" in y or "FinanceCosts" in y) else None))
    put("pbt", lambda y: _first(y, ["ProfitLossBeforeTax"]))
    put("net_total", lambda y: _first(y, ["ProfitLoss", "ProfitLossFromContinuingOperations"]))
    put("net", lambda y: _first(y, ["ProfitLossAttributableToOwnersOfParent"]) if "ProfitLossAttributableToOwnersOfParent" in y
        else _first(y, ["ProfitLoss"]))
    # tax and minorities derived from subtotals: robust to sign conventions
    L["tax"] = [None if p is None or t is None else p - t for p, t in zip(L["pbt"], L["net_total"])]
    L["nci"] = [None if t is None or n is None else t - n for t, n in zip(L["net_total"], L["net"])]
    L["other_pre_tax"] = [None if p is None or e is None else p - e for p, e in zip(L["pbt"], L["ebit"])]
    put("eps", lambda y: _first(y, ["BasicEarningsLossPerShare"]))

    # balance sheet
    put("assets", lambda y: _first(y, ["Assets"]))
    put("equity", lambda y: _first(y, ["Equity"]))
    put("equity_parent", lambda y: _first(y, ["EquityAttributableToOwnersOfParent", "Equity"]))
    put("inventories", lambda y: _first(y, ["InventoriesTotal", "Inventories", "CurrentInventoriesHeldForSale"], True))
    put("receivables", lambda y: _first(y, ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables",
                                            "TradeAndOtherReceivables"], True))
    put("payables", lambda y: _first(y, ["TradeAndOtherCurrentPayables", "TradeAndOtherCurrentPayablesToTradeSuppliers", "TradeAndOtherPayablesToTradeSuppliers",
                                         "CurrentTradePayables", "TradeAndOtherPayables"], True))
    put("cash", lambda y: _first(y, ["CashAndCashEquivalents"]))
    put("st_investments", lambda y: _first(y, ["ShorttermDepositsNotClassifiedAsCashEquivalents", "CurrentInvestments"], True))

    def borrowings(y):
        nc = _first(y, ["LongtermBorrowings", "NoncurrentPortionOfNoncurrentBorrowings"], True)
        if nc is None:
            nc = _sum(y, ["NoncurrentPortionOfNoncurrentBondsIssued", "NoncurrentPortionOfNoncurrentLoansReceived",
                          "NoncurrentPortionOfNoncurrentBankLoansReceived", "NoncurrentPortionOfNoncurrentNotesAndDebenturesIssued"])
        c = _first(y, ["CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"], True)
        if c is None:
            c = _sum(y, ["ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings", "CurrentPortionOfNoncurrentBondsIssued",
                         "CurrentPortionOfNoncurrentLoansReceived", "CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
                         "CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived"])
        if nc is None and c is None:
            return None
        return (nc or 0) + (c or 0)
    put("borrowings", borrowings)
    put("lease_liabilities", lambda y: _sum(y, ["NoncurrentLeaseLiabilities", "CurrentLeaseLiabilities"]) if (
        "NoncurrentLeaseLiabilities" in y or "CurrentLeaseLiabilities" in y) else _first(y, ["LeaseLiabilities"], True))

    # cash flow
    put("ocf", lambda y: _first(y, ["CashFlowsFromUsedInOperatingActivities"]))
    put("capex", lambda y: _first(y, ["PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"], True)
        if "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets" in y
        else _sum(y, ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                      "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
                      "PurchaseOfPropertyPlantAndEquipment", "PurchaseOfIntangibleAssets"]))
    put("lease_payments", lambda y: _first(y, ["PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities",
                                               "PaymentsOfFinanceLeaseLiabilitiesClassifiedAsFinancingActivities"], True))
    put("dividends", lambda y: _first(y, ["DividendsPaidClassifiedAsFinancingActivities",
                                          "DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities",
                                          "DividendsPaid"], True))
    # drop lines that are empty in every year
    return {k: v for k, v in L.items() if any(x is not None for x in v)}
