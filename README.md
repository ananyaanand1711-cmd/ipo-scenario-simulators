# IPO Scenario Simulator & Research

An offline-first Streamlit research workspace for Indian Mainboard and SME IPOs. It includes a dashboard, IPO research view, financial analysis, user-driven scenario simulator, CSV/manual data management, and a methodology page.

## Data and safety

The bundled rows are synthetic examples marked `DEMONSTRATION ONLY`. They are not real IPOs and must never be treated as actual company figures, subscription data, GMP, or listing prices. No source refresh runs automatically. Data Management has one best-effort NSE Issue Information lookup. One live NSE request succeeded on 20 October 2026, while earlier requests in the same environment failed DNS resolution. Availability is intermittent, the endpoint is undocumented, and its response is review-required rather than independently verified. This app does not claim complete Mainboard/SME coverage. Manual forms and CSV imports remain the fallback. See [SOURCES.md](SOURCES.md) for the tested request, timestamp, mapped fields, verification limits, and manual-only sources.

## Local launch (Windows PowerShell)

Open PowerShell in the project folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

The final line is the exact launch command after activating the project environment. Open the local URL printed by Streamlit (usually `http://localhost:8501`). If PowerShell blocks activation, use the venv interpreter directly: `.\.venv\Scripts\python.exe -m streamlit run app.py`.

To run the full test suite after activation:

```powershell
python -m pytest -q
```

## Data management

The four CSV files in `data/` define the starter datasets. Manual IPO edits/additions, annual financial entries, subscription observations, CSV replacements, and reviewed NSE drafts are validated and written atomically back to their matching files in `data/`. Download buttons export the current saved data. IPO master IDs must be unique; financial periods and subscription observation keys are checked for duplicates. Unknown measurements remain blank and can be left blank in CSV imports.

The sidebar **Active IPO** selection is shared across research, financial analysis, subscriptions and scenario simulation. Dashboard filters and search apply to the same underlying saved master records. Financial charts and derived growth, margin, leverage and valuation metrics recalculate from the selected IPO's saved rows. Simulator inputs recalculate on every change, and **Reset to selected IPO values** restores its saved issue price and lot size with fresh user-assumption scenarios.

### Data Management workflow

Open **Data Management** and use the tabs for IPO details, financial statements, subscriptions, peers, and source documents. Each tab supports add/edit and confirmed deletion where available. Download the matching CSV template for the required headers. CSV import shows a validated preview and detects duplicate keys both inside the file and against saved data; imports append new rows only, so they cannot overwrite existing VERIFIED records. Download the current dataset backup and confirm that backup before enabling a bulk import. Manual and CSV changes add a provenance history row with source URL, observation date, reporting period, data status, and UTC last-updated time. NSE refresh is manual, reports its real result, and never silently replaces saved data.
### Local storage and public deployment limits

Local edits persist across browser refreshes and app restarts because the app writes the CSVs in `data/`. Back up those files and commit or otherwise retain the updated CSVs if you need an external copy. When deployed on Streamlit Community Cloud or another multi-user host, local files are not a reliable shared database: app rebuilds/redeployments can replace filesystem edits, replicas may have separate files, and concurrent users can overwrite each other's changes. Use a persistent mounted volume or a database with access control and backups for production shared use. Do not place secrets in these data files.

### Feature verification

Run `python -m pytest -q` after activating the local virtual environment. Tests cover saved CSV reload after a simulated restart, duplicate-ID rejection, import/export round trips, missing values, derived financial edge cases, and scenario output changes. For an interactive check, launch the app and: add an IPO in **Data Management**, refresh the browser and confirm it remains; edit one of its fields and confirm **Dashboard** and **IPO Research** reflect it; add two annual records and inspect the recalculated table/chart in **Financial Analysis**; enter subscription categories and verify the research table/chart; change scenario issue price, lot size, lots, and assumptions and confirm the summary/table/chart/sensitivity update, then use reset; download a CSV and re-import it to check round-trip behavior.
Required columns:

| Dataset | Required columns |
|---|---|
| `ipo_master` | `ipo_id,company_name,segment,exchange,status,open_date,close_date,issue_price,price_band_low,price_band_high,lot_size,issue_size_crore,fresh_issue_crore,offer_for_sale_crore,listing_price,listing_date,sector,drhp_url,rhp_url,source_url,source_date,data_status` |
| `financials` | `ipo_id,financial_year,revenue_crore,ebitda_crore,pat_crore,total_borrowings_crore,net_worth_crore,eps,source_url,source_date,data_status` |
| `subscription` | `ipo_id,category,subscription_multiple,as_of` |
| `peers` | `ipo_id,peer_name,period,market_cap_cr,revenue_cr,pat_cr` |

The IPO master uses `segment` values `Mainboard` or `SME`; `status` values `Upcoming`, `Open`, `Closed`, or `Listed`; and `data_status` values `DEMO`, `VERIFIED`, or `MANUAL`. VERIFIED rows must include a source URL and source date. Empty listing price is valid until an actual price is verified. Dates use `YYYY-MM-DD`; currency and issue-size columns are numeric, with issue sizes in INR crore.

Financial records support multiple `financial_year` rows per IPO. The `*_crore` fields are numeric INR crore amounts, while `eps` is INR per share. Leave unknown values blank; the app displays them as unavailable and does not fill or estimate company financials. VERIFIED financial rows require `source_url` and `source_date`. The app warns about duplicate/mixed/skipped annual periods and reminds users that numeric values alone cannot reveal a mistaken unit scale.

Derived financial metrics are labeled and show their formulas: PAT margin = PAT / revenue × 100 when revenue is positive; debt-to-equity = total borrowings / net worth when net worth is positive; P/E = user-entered market price / EPS only when both are positive. No market price is fetched. Undefined metrics remain unavailable.

## Scenario simulator

Enter a positive issue price per share, whole-number lot size and number of lots, then supply Bear, Base, and Bull listing-price assumptions. If the selected saved IPO has no issue price, the control starts blank; the app does not substitute the price-band high or another value. Every listing-price assumption is labeled as user supplied and is not predicted or guaranteed. Investment = issue price × lot size × lots; shares = lot size × lots; scenario value = assumed listing price × shares; gross P/L = scenario value − investment; gross return = gross P/L ÷ investment × 100; break-even price = investment ÷ shares. The comparison chart and sensitivity table use the same gross calculations. Optional transaction cost and tax percentages plus fixed charges are off by default. If enabled, each percentage is applied to both investment and scenario sale value; fixed charges are applied once. Optional net P/L = gross P/L − percentage charges − fixed charges. Confirm your applicable costs and tax treatment independently. The simulator is for educational use and does not provide investment advice.

## GitHub and Streamlit Community Cloud deployment

### 1. Create and push the GitHub repository

1. On GitHub, create a **new empty repository**. Do not initialize it with a README, license, or `.gitignore`; this project already has those files.
2. Authenticate Git using Git Credential Manager or `gh auth login`. Complete sign-in in the browser when prompted. Never paste a password, token, API key, or Streamlit secret into a command or source file.
3. From PowerShell in this project folder, initialize and push the application. Replace `<OWNER>` and `<REPOSITORY>` with the GitHub account/organization and repository name you created:

```powershell
git init -b main
git add app.py README.md SOURCES.md requirements.txt pytest.ini .gitignore .streamlit/config.toml data src tests
git status --short
git commit -m "Prepare IPO research app for deployment"
git remote add origin https://github.com/<OWNER>/<REPOSITORY>.git
git push -u origin main
```

If `git remote add origin` reports that `origin` already exists, inspect it with `git remote -v` and use the existing correct remote; do not add a second remote with the same name. Review `git status --short` before committing. `.venv/`, test scratch files, Streamlit secrets, and the local retrieval log are excluded by `.gitignore`.

### 2. Deploy the GitHub repository to Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io/) with GitHub. Authorize Streamlit to access the repository; deploying requires repository admin access.
2. In the Community Cloud workspace, select **Create app**, then **Yup, I have an app**.
3. Choose the GitHub owner/repository, branch `main`, and main file path `app.py`.
4. Open **Advanced settings** and select Python 3.12, matching the locally tested Python 3.12.14 (`.venv\Scripts\python.exe --version`). Choose the version deliberately because changing Python after deployment requires deleting and redeploying the app.
5. Leave **Secrets** empty. This application has no API keys or credentials. Select **Deploy** and wait for the build to finish; Community Cloud installs dependencies from the repository's `requirements.txt`.
6. Open the generated `*.streamlit.app` URL. Check the deployment logs if the build or app fails. The NSE refresh is user initiated and needs outbound access to NSE; CSV import and manual entry remain available when NSE is unavailable.

### 3. Publish later updates

From the project folder, review the changes and push them to the deployed branch:

```powershell
git status --short
git add app.py README.md SOURCES.md requirements.txt pytest.ini .gitignore .streamlit/config.toml data src tests
git commit -m "Describe the update"
git push
```

Community Cloud watches the configured GitHub branch and rebuilds the app after a push. Treat browser uploads and `data/retrieval_log.csv` as instance-local; use CSV downloads and a controlled source-data repository when persistence is needed. See Streamlit's official guides for [deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization), and [dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

## Project layout

```text
app.py
requirements.txt
README.md
.gitignore
.streamlit/
  config.toml
data/
  ipo_master.csv
  financials.csv
  subscription.csv
  peers.csv
src/
  __init__.py
  data_loader.py
  calculations.py
  scenario.py
  research.py
  retrieval/
    __init__.py
    base.py
    nse.py
    storage.py
tests/
  test_calculations.py
  test_data_loader.py
  test_research.py
  test_scenario.py
  test_retrieval.py
SOURCES.md
```

## Disclaimers

This software is for research and educational use. Scenario prices are arithmetic outputs of assumptions supplied by the user, not predictions. Verify source data and consult a qualified financial professional as appropriate. The application does not provide investment advice.
