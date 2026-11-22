# Expense Monitor

Daily household expense book: add expenses every day, get the monthly Word file
(day-wise, NIL on empty days, summary by head) and custom reports (any dates, heads, words).

Same setup as equity-portfolio-app: Streamlit + Postgres, password-protected, hosted on Render.

## Render settings
- Build: `pip install -r requirements.txt`
- Start: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
- Environment variables:
  - `EXPENSE_PASSWORD` – login password
  - `DATABASE_URL` – Postgres connection string (data survives redeploys)

On first start with an empty database, September and October 2026 are loaded from
`seed_sep_oct_2026.json`. Without `DATABASE_URL` it uses a local `expenses.db` file (for testing).

## Run locally
    pip install -r requirements.txt
    streamlit run app.py
