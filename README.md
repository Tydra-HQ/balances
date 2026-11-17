# Balances

Management reports for Spanish listed companies, built automatically from their official annual filings.

Pick a company and the app shows a management-style report: key figures with 5-year mini trends, key messages, the 5-year trend, margins, the income statement, a net income bridge, working capital, cash generation, balance sheet ratios and points to watch. English and Spanish.

## How it works

1. **Source.** Listed companies in the EU file their consolidated annual reports in the European ESEF format, with every figure tagged with an IFRS code (for example `ifrs-full:Revenue`). In Spain they are filed with the CNMV. The pipeline reads them from the public archive [filings.xbrl.org](https://filings.xbrl.org), which publishes each filing in xBRL-JSON.
2. **Mapping** (`pipeline/mapping.py`). IFRS codes are mapped to a standard set of lines, with fallbacks, because companies present their accounts differently. Only consolidated totals are used (no segment breakdowns).
3. **Calculations** (`pipeline/build.py`). Margins, growth, EBITDA (operating profit + depreciation and amortisation), working capital and days, free cash flow, net cash or debt, return on equity, leverage.
4. **Messages** (`pipeline/rules.py`). Fixed rules turn the numbers into key messages and points to watch, in English and Spanish. No AI: every number in a sentence comes from the data.
5. **App** (`index.html`, `app.js`, `styles.css`). A plain JavaScript PWA that reads `data/*.json`. No build step.

A GitHub Actions workflow (`.github/workflows/build-and-deploy.yml`) runs the pipeline on every push, on the 3rd of each month and on demand, commits the updated data and publishes the site to GitHub Pages.

## Companies

Edit `pipeline/companies.json` to add companies (ticker, names, LEI, sector). Non-financial companies only for now: banks and insurers need a different template.

## Run locally

```bash
pip install requests
python pipeline/build.py          # all companies
python pipeline/build.py ITX      # one company
python -m http.server 8000        # then open http://localhost:8000
```

## Notes

- Figures are as tagged by each company. Prior years use the latest filing that reports them (restated where applicable).
- Net cash = cash + short-term deposits − financial borrowings; lease liabilities are excluded.
- Not investment advice.

Copyright © 2026. All rights reserved.
