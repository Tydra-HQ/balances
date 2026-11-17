"""
Rules that turn the numbers into key messages and points to watch, in
English and Spanish. No AI: each rule checks a condition on the figures and,
if it applies, fills in a sentence template. Every number in a sentence comes
from the data, so the text can always be traced back to the filing.

Each rule returns (priority, english, spanish) or None. The highest
priorities are shown. To add your own criteria, add a function to
HIGHLIGHT_RULES or WATCH_RULES.
"""


# ---------------------------------------------------------------- formatting

def _num(v, dec, lang):
    s = f"{abs(v):,.{dec}f}"
    if lang == "es":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        # Spanish style does not group 4-digit numbers
        if dec == 0 and 1000 <= abs(v) < 10000:
            s = s.replace(".", "")
    return ("−" if v < 0 else "") + s


def money(v, lang, cur="EUR"):
    sym = "€" if cur == "EUR" else cur + " "
    if lang == "en":
        if abs(v) >= 1000:
            return ("−" if v < 0 else "") + f"{sym}{_num(abs(v) / 1000, 1, 'en')}bn"
        return ("−" if v < 0 else "") + f"{sym}{_num(abs(v), 0, 'en')}m"
    unit = "M€" if cur == "EUR" else f"M {cur}"
    return f"{_num(v, 0, 'es')} {unit}"


def pct(v, lang, signed=False):
    s = _num(abs(v), 1, lang) + "%"
    if signed:
        return ("+" if v >= 0 else "−") + s
    return ("−" if v < 0 else "") + s


def pts(v, lang):
    word = "points" if lang == "en" else "puntos"
    return ("+" if v >= 0 else "−") + _num(abs(v), 1, lang) + " " + word


# ---------------------------------------------------------------- helpers

class Ctx:
    def __init__(self, d):
        self.d = d
        self.L = d["lines"]
        self.M = d["metrics"]
        self.n = len(d["years"])
        self.cur = d.get("currency", "EUR")
        self.years = d["years"]

    def line(self, k, i=-1):
        v = self.L.get(k)
        return None if not v else v[i]

    def met(self, k, i=-1):
        v = self.M.get(k)
        return None if not v else v[i]

    def g(self, k):
        a, b = self.line(k, -1), self.line(k, -2)
        if a is None or b in (None, 0) or b < 0:
            return None
        return (a / b - 1) * 100

    def m(self, v, lang):
        return money(v, lang, self.cur)


# ---------------------------------------------------------------- highlight rules

def r_revenue(c):
    r, g = c.line("revenue"), c.g("revenue")
    if r is None or g is None:
        return None
    if g >= 0:
        return 100, f"Revenue grew {pct(g, 'en')} to {c.m(r, 'en')}.", f"Los ingresos crecieron un {pct(g, 'es')} hasta {c.m(r, 'es')}."
    return 100, f"Revenue fell {pct(-g, 'en')} to {c.m(r, 'en')}.", f"Los ingresos cayeron un {pct(-g, 'es')} hasta {c.m(r, 'es')}."


def r_revenue_long(c):
    rv = c.L.get("revenue")
    if not rv or c.n < 3 or rv[0] in (None, 0) or rv[-1] is None or rv[0] < 0:
        return None
    k = c.n - 1
    tot = (rv[-1] / rv[0] - 1) * 100
    cagr = ((rv[-1] / rv[0]) ** (1 / k) - 1) * 100
    en_v = "grew" if tot >= 0 else "fell"
    es_v = "crecieron" if tot >= 0 else "cayeron"
    return (70,
            f"Since {c.years[0]}, revenue {en_v} {pct(abs(tot), 'en')} ({pct(cagr, 'en', True)} a year on average).",
            f"Desde {c.years[0]}, los ingresos {es_v} un {pct(abs(tot), 'es')} ({pct(cagr, 'es', True)} anual de media).")


def r_ebitda_margin(c):
    m1, m0 = c.met("ebitda_margin", -1), c.met("ebitda_margin", -2)
    if m1 is None or m0 is None:
        return None
    d = m1 - m0
    go, gr = c.g("opex"), c.g("revenue")
    if go is not None and gr is not None and 0 <= go < gr and d > 0:
        return (90,
                f"Operating expenses grew {pct(go, 'en')}, less than revenue ({pct(gr, 'en')}): EBITDA margin rose to {pct(m1, 'en')} ({pts(d, 'en')}).",
                f"Los gastos operativos crecieron un {pct(go, 'es')}, menos que los ingresos ({pct(gr, 'es')}): el margen EBITDA subió al {pct(m1, 'es')} ({pts(d, 'es')}).")
    if abs(d) < 0.2:
        return (75, f"EBITDA margin stable at {pct(m1, 'en')}.", f"Margen EBITDA estable en el {pct(m1, 'es')}.")
    en_v, es_v = ("rose", "subió") if d > 0 else ("fell", "bajó")
    return (85, f"EBITDA margin {en_v} to {pct(m1, 'en')} ({pts(d, 'en')}).", f"El margen EBITDA {es_v} al {pct(m1, 'es')} ({pts(d, 'es')}).")


def r_gross_margin(c):
    m1, m0 = c.met("gross_margin", -1), c.met("gross_margin", -2)
    if m1 is None or m0 is None or abs(m1 - m0) < 0.2:
        return None
    d = m1 - m0
    en_v, es_v = ("widened", "se amplió") if d > 0 else ("narrowed", "se redujo")
    return 60, f"Gross margin {en_v} to {pct(m1, 'en')} ({pts(d, 'en')}).", f"El margen bruto {es_v} hasta el {pct(m1, 'es')} ({pts(d, 'es')})."


def r_net(c):
    ni, g = c.line("net"), c.g("net")
    if ni is None:
        return None
    series = [v for v in c.L.get("net", []) if v is not None]
    if ni < 0:
        return 95, f"Net result was a loss of {c.m(-ni, 'en')}.", f"El resultado neto fue una pérdida de {c.m(-ni, 'es')}."
    rec_en = f", the highest of the last {len(series)} years" if len(series) >= 3 and ni >= max(series) else ""
    rec_es = f", el más alto de los últimos {len(series)} años" if rec_en else ""
    if g is None:
        return 80, f"Net income of {c.m(ni, 'en')}{rec_en}.", f"Beneficio neto de {c.m(ni, 'es')}{rec_es}."
    if g >= 0:
        return 95, f"Net income rose {pct(g, 'en')} to {c.m(ni, 'en')}{rec_en}.", f"El beneficio neto subió un {pct(g, 'es')} hasta {c.m(ni, 'es')}{rec_es}."
    return 95, f"Net income fell {pct(-g, 'en')} to {c.m(ni, 'en')}.", f"El beneficio neto bajó un {pct(-g, 'es')} hasta {c.m(ni, 'es')}."


def r_working_capital(c):
    owc = c.met("owc")
    if owc is None:
        return None
    if owc < 0:
        return (50,
                f"Operating working capital is negative ({c.m(owc, 'en')}): suppliers finance inventories and customer receivables.",
                f"El capital circulante operativo es negativo ({c.m(owc, 'es')}): los proveedores financian existencias y cobros.")
    return (35,
            f"Operating working capital of {c.m(owc, 'en')} ties up {pct(owc / c.line('revenue') * 100, 'en')} of revenue." if c.line("revenue") else None,
            f"El capital circulante operativo de {c.m(owc, 'es')} inmoviliza el {pct(owc / c.line('revenue') * 100, 'es')} de los ingresos." if c.line("revenue") else None) if c.line("revenue") else None


def r_net_cash(c):
    nc = c.met("net_cash")
    if nc is None:
        return None
    if nc >= 0:
        return (65,
                f"Net cash of {c.m(nc, 'en')}: more cash and deposits than financial debt (leases excluded).",
                f"Caja neta de {c.m(nc, 'es')}: más caja y depósitos que deuda financiera (sin arrendamientos).")
    lev = c.met("net_debt_ebitda")
    tail_en = f", {_num(lev, 1, 'en')} times EBITDA" if lev is not None else ""
    tail_es = f", {_num(lev, 1, 'es')} veces el EBITDA" if lev is not None else ""
    return (65, f"Net financial debt of {c.m(-nc, 'en')}{tail_en} (leases excluded).",
            f"Deuda financiera neta de {c.m(-nc, 'es')}{tail_es} (sin arrendamientos).")


def r_fcf(c):
    f, dv = c.met("fcf"), c.line("dividends")
    if f is None:
        return None
    if dv:
        return (55, f"Free cash flow after investment and leases: {c.m(f, 'en')}; dividends paid: {c.m(dv, 'en')}.",
                f"Flujo de caja libre tras inversiones y arrendamientos: {c.m(f, 'es')}; dividendos pagados: {c.m(dv, 'es')}.")
    return 50, f"Free cash flow after investment and leases: {c.m(f, 'en')}.", f"Flujo de caja libre tras inversiones y arrendamientos: {c.m(f, 'es')}."


def r_roe(c):
    r = c.met("roe")
    if r is None or r < 15:
        return None
    return 40, f"Return on equity of {pct(r, 'en')}.", f"Rentabilidad sobre fondos propios del {pct(r, 'es')}."


HIGHLIGHT_RULES = [r_revenue, r_net, r_ebitda_margin, r_revenue_long, r_net_cash, r_gross_margin, r_fcf, r_working_capital, r_roe]


# ---------------------------------------------------------------- watch rules

def w_revenue_down(c):
    g = c.g("revenue")
    if g is None or g >= 0:
        return None
    return 100, f"Revenue is falling ({pct(g, 'en', True)}).", f"Los ingresos caen ({pct(g, 'es', True)})."


def w_margin_down(c):
    m1, m0 = c.met("ebitda_margin", -1), c.met("ebitda_margin", -2)
    if m1 is None or m0 is None or m1 - m0 > -1:
        return None
    return 90, f"EBITDA margin dropped {pts(m1 - m0, 'en')}.", f"El margen EBITDA cayó {pts(m1 - m0, 'es')}."


def w_net_down(c):
    ni, g = c.line("net"), c.g("net")
    if ni is not None and ni < 0:
        return 95, "The company is loss-making this year.", "La empresa tiene pérdidas este año."
    if g is None or g > -5:
        return None
    return 85, f"Net income fell {pct(-g, 'en')}.", f"El beneficio neto bajó un {pct(-g, 'es')}."


def w_leverage(c):
    lev = c.met("net_debt_ebitda")
    if lev is None or lev < 2:
        return None
    level_en = "high" if lev >= 3 else "moderate"
    level_es = "elevado" if lev >= 3 else "moderado"
    return (80 if lev >= 3 else 60,
            f"Debt level is {level_en}: net financial debt is {_num(lev, 1, 'en')} times EBITDA.",
            f"Endeudamiento {level_es}: la deuda financiera neta equivale a {_num(lev, 1, 'es')} veces el EBITDA.")


def w_dividends_over_fcf(c):
    f, dv = c.met("fcf"), c.line("dividends")
    if f is None or not dv or dv <= f:
        return None
    return (75, f"Dividends paid ({c.m(dv, 'en')}) exceeded free cash flow ({c.m(f, 'en')}): the difference came from cash reserves or debt.",
            f"Los dividendos pagados ({c.m(dv, 'es')}) superaron el flujo de caja libre ({c.m(f, 'es')}): la diferencia salió de la caja o de deuda.")


def w_fcf_down(c):
    f1, f0 = c.met("fcf", -1), c.met("fcf", -2)
    if f1 is None or f0 is None or f0 <= 0:
        return None
    g = (f1 / f0 - 1) * 100
    if g > -10:
        return None
    return 70, f"Free cash flow fell {pct(-g, 'en')} ({c.m(f1, 'en')} vs {c.m(f0, 'en')}).", f"El flujo de caja libre bajó un {pct(-g, 'es')} ({c.m(f1, 'es')} vs. {c.m(f0, 'es')})."


def w_fcf_small(c):
    f1, f0 = c.met("fcf", -1), c.met("fcf", -2)
    if f1 is None or f0 is None or f0 <= 0:
        return None
    g = (f1 / f0 - 1) * 100
    if not -10 < g < -1:
        return None
    return 45, f"Free cash flow dipped {pct(-g, 'en')} ({c.m(f1, 'en')} vs {c.m(f0, 'en')}).", f"El flujo de caja libre bajó un {pct(-g, 'es')} ({c.m(f1, 'es')} vs. {c.m(f0, 'es')})."


def w_net_cash_down(c):
    a, b = c.met("net_cash", -1), c.met("net_cash", -2)
    if a is None or b is None or a >= b:
        return None
    return (50, f"Net cash/(debt) worsened by {c.m(b - a, 'en')} in the year.",
            f"La posición financiera neta empeoró en {c.m(b - a, 'es')} en el año.")


def w_equity_ratio(c):
    r = c.met("equity_ratio")
    if r is None or r >= 20:
        return None
    return 65, f"Equity is only {pct(r, 'en')} of total assets.", f"Los fondos propios son solo el {pct(r, 'es')} del activo total."


def w_collection_days(c):
    a, b = c.met("days_rec", -1), c.met("days_rec", -2)
    if a is None or b is None or a - b < 10:
        return None
    return 55, f"Customers are taking longer to pay: {round(a)} days vs {round(b)}.", f"Los clientes tardan más en pagar: {round(a)} días vs. {round(b)}."


WATCH_RULES = [w_revenue_down, w_margin_down, w_net_down, w_leverage, w_dividends_over_fcf,
               w_fcf_down, w_fcf_small, w_net_cash_down, w_equity_ratio, w_collection_days]


def _run(rules, c, k):
    out = []
    for rule in rules:
        try:
            res = rule(c)
        except Exception:
            res = None
        if res and res[1] and res[2]:
            out.append(res)
    out.sort(key=lambda r: -r[0])
    return out[:k]


def build_messages(data):
    c = Ctx(data)
    hl = _run(HIGHLIGHT_RULES, c, 5)
    wt = _run(WATCH_RULES, c, 3)
    if not wt:
        wt = [(0, "No warning signs in this year's figures.", "Sin señales de alerta en las cifras de este año.")]
    return {
        "en": {"highlights": [h[1] for h in hl], "watch": [w[1] for w in wt]},
        "es": {"highlights": [h[2] for h in hl], "watch": [w[2] for w in wt]},
    }
