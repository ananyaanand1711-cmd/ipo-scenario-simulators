# IPO source coverage and retrieval limits

Reviewed 20 October 2026. The application implements one source adapter: NSE Issue Information. It is a best-effort, user-triggered lookup, not complete Mainboard or SME coverage. Other official pages are reference sources only and require manual review/entry or CSV import.

## Implemented source: NSE Issue Information

- Human-readable official source: [NSE Issue Information](https://www.nseindia.com/market-data/issue-information).
- Observed detail request: first `GET https://www.nseindia.com/market-data/issue-information?series={EQ|SME}&symbol={SYMBOL}`, then `GET https://www.nseindia.com/api/ipo-detail?symbol={SYMBOL}&series={EQ|SME}`. The adapter sends ordinary HTTPS requests with a 12-second timeout, a one-second shared minimum interval, and normal page referer headers. HTTP 429, 401/403, timeouts, request errors, non-JSON responses, malformed response shapes, and symbol mismatches fail closed with user-facing errors. It does not authenticate, solve CAPTCHAs, evade protections, or retry access denials.
- The JSON route is an observed website endpoint, not a documented or guaranteed public API contract. Request/query construction and returned-field mapping are covered by fake-response contract tests. A live request succeeded on 20 October 2026 at `2026-10-20T11:41:25Z` for `ZETWERK/EQ`. The observed reporting period was `15-Oct-2026 to 19-Oct-2026`; the source URL was `https://www.nseindia.com/api/ipo-detail?symbol=ZETWERK&series=EQ`. The adapter returned company name, requested symbol, Mainboard segment (based on the requested `EQ` series), offer dates, price band (INR 143–151), and lot size (99). It returned sector, listing date, issue size, issue price and listing price as unavailable. This validates that the request path and expected JSON shape worked at that timestamp only; each source response remains `SOURCE_RESPONSE_VALIDATED_REVIEW_REQUIRED`, not independently verified, and this transient observation was not added to the app's datasets. Network availability can vary by time and deployment host. Earlier DNS failures do not negate this later successful request.

### Fields and limits

| Field | Mapping / source | Limit |
|---|---|---|
| Company name | `metaInfo.companyName`, top-level `companyName`, or a non-`Symbol` title in `issueInfo.dataList` | Fails if no name can be resolved. |
| NSE symbol | `metaInfo.symbol` or `issueInfo.symbol` | Must match the requested symbol. |
| Segment | Uses returned `metaInfo.segment` when recognized; otherwise maps the user's selected NSE series (`EQ` or `SME`) | Series-derived fallback is request context, not an independent returned fact. Review it. |
| Sector | `metaInfo.industry` | Often absent; blank remains unavailable. |
| Listing date | `metaInfo.listingDate` only when already `YYYY-MM-DD` | May be absent; never converted from ambiguous text. |
| Open/close dates | Parsed from `Issue Period` in the issue detail list | Available only when exactly two recognized dates occur. |
| Price band low/high | First two numeric values in `Price Range` | The adapter fails closed on missing/ambiguous value counts by leaving the fields unavailable; review the original source. |
| Lot size | First integer in `Bid Lot` | May be absent or format may change. |
| Issue size in INR crore | Not mapped | Narrative can combine shares/amounts and is not safely normalized. Enter from the offer document. |
| Issue price | Not mapped | Do not infer from the band. |
| Listing price, financials, subscription multiples, GMP | Not mapped | No values are invented or inferred. NSE's page may display bid information, but the adapter does not retrieve or normalize subscription figures. |
| DRHP/RHP links, status, fresh issue/OFS split | Not mapped | Enter after checking the official issue documents/disclosures. |

A successful response receives `SOURCE_RESPONSE_VALIDATED_REVIEW_REQUIRED`. That status means the response was JSON, had the expected field containers, and matched the requested symbol. It does **not** mean the underlying disclosure was independently verified. The source URL, UTC retrieval timestamp, reporting period when parsed, response fields, success/failure, and message are appended to `data/retrieval_log.csv`. Retrievals older than seven days display as stale; missing supported values display as incomplete. A refresh never writes into IPO, financial, subscription, or peer datasets. On success, manually review against the linked NSE page and enter values through Data Management; on failure, retry later or use the manual/CSV workflow.

Refresh frequency is manual and on demand; no scheduled polling runs. The adapter enforces a one-second minimum between HTTP requests, but this is not permission to poll aggressively. Avoid repeated requests, and stop if NSE returns 429, 401, or 403. The NSE eIPO member APIs require member access/approval and are not used by this app; see [NSE e-IPO FAQs](https://www.nseindia.com/static/trade/e-ipo-faqs).

## Public primary sources that require manual review

| Source | Appropriate use | App connector |
|---|---|---|
| [NSE Issue Information](https://www.nseindia.com/market-data/issue-information) | Mainboard/SME issue facts and public issue documents where shown | One best-effort adapter described above; current runtime DNS failure prevents live requests. |
| [BSE Public Issues](https://www.bseindia.com/markets/publicIssues/DisplayIPO.aspx) | BSE issue information, offer documents and notices | No connector. No stable, accessible public machine-readable contract and returned field set has been verified in this project. |
| [SEBI Public Issues filings](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15) and [SEBI filings](https://www.sebi.gov.in/filings.html) | DRHP, RHP, prospectuses, addenda and filing information | No connector. Documents and page structures require human review; do not treat a filing as normalized data. |
| Issuer investor-relations annual reports and exchange-filed financial results | Annual/periodic financial statements and reporting periods | No universal connector. Enter/import values with exact period, INR crore units (EPS INR/share), source URL/date and status. |
| Official exchange bid/subscription disclosures | Category-level QIB/NII/retail bids where published | No connector. Enter only a dated, sourced observation; figures can change during the issue window. |

## Manual fallback and completeness

Use Data Management forms or the supplied CSV templates when NSE is unreachable or a field is not mapped. Check the prospectus/exchange filing for issue size, fresh issue/OFS split, issue price, offer dates, listing status, listing price, DRHP/RHP URLs and lot size. Check audited reports/results for financial data and record the fiscal period. Record subscription figures with category, source URL and observation date. Do not enter GMP or a listing price without an actual source; the scenario simulator's listing prices are user assumptions only. Mark values `MANUAL` until a person has checked their primary source and provenance; only then use `VERIFIED`.

No API credentials are needed for the implemented NSE request. If a future provider requires credentials, keep them in environment variables or Streamlit secrets, never source code or CSV exports. This implementation does not claim complete automatic Mainboard or SME IPO coverage.
