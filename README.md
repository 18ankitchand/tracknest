# TrackNest / Expanse Tracker — Django authentication, monthly budgets and email alerts

## Local setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations accounts
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000/. Existing sign-in/sign-up and dashboard UI are preserved.

## Budget behavior
The registered user's email is stored in Django's User.email. Transaction records and monthly budget limits are stored per authenticated user in SQLite. When an accepted expense brings this month's spending exactly to the limit, TrackNest blocks subsequent expense records and queues a limit-reached email. An expense that would exceed the limit is rejected and not saved. The alert is sent only once per user/month. The budget may be increased by the user. Budget enforcement applies only to TrackNest records, never external payments.

## Email testing
By default Django uses the console email backend. The alert appears in the `runserver` terminal; **no real email is sent**.

To send real email, configure SMTP credentials via environment variables (do not commit passwords):
```
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_USE_TLS=1
DJANGO_EMAIL_HOST_USER=your-sender@gmail.com
DJANGO_EMAIL_HOST_PASSWORD=your-app-password
DJANGO_DEFAULT_FROM_EMAIL=your-sender@gmail.com
```
For Gmail, use an app password on an eligible account with 2-Step Verification, not your regular Gmail password. In production, use a transactional email provider and a background task queue, rather than sending SMTP in the request callback. Add email verification to ensure addresses belong to registrants before sending alerts.

## Caveats
This is a development starter, not a deployed service. Email delivery, concurrency behavior (especially SQLite), and Django runtime have not been verified here. The email is queued on transaction commit, but the current synchronous callback can still fail after a transaction is saved; production should use an outbox and worker. Income/expense data is saved; dashboard forecasting and AI assistant remain demos. Set DEBUG=0, a strong SECRET_KEY, secure cookies and HTTPS before deployment. Do not assume the registered email is verified.

## Updated interface and administrator reporting
- The Sign In and Create Account screens have a new two-column responsive layout. Technical marketing copy such as “Secure Django REST API & Forecasting” has been removed from the login screen.
- Registered users and saved expenses are already represented by Django's `auth.User` and `accounts.ExpenseTransaction`; SQLite stores records in `db.sqlite3` after migrations. The ZIP intentionally does **not** contain any real user data.
- An administrator can view user counts, saved expense counts, and total expenses in Nrs at **http://127.0.0.1:8000/admin/overview/**. The report includes historical recorded expense amounts across all dates, not just the current month. Income is not counted as an expense. Staff accounts are included in the full accounts total but excluded from the registered-user count.
- The regular Django administration at `/admin/` has searchable user, transaction, profile and monthly budget views. Transaction and budget records are read-only there to avoid bypassing validation and budget rules.
- Users cannot access the admin overview without a staff account. Ordinary user financial APIs still filter to `request.user`.

### Set up the database and admin login
```bash
python manage.py makemigrations accounts
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Open the website at `http://127.0.0.1:8000/` and sign up to create user records. Then log into the admin using the superuser account at `/admin/overview/`. The site does not create or ship any fake user accounts.

### Tests
```bash
python manage.py check
python manage.py test accounts
```
These tests verify administrator access, global sums, per-user totals, user data isolation, and budget rejection. Install requirements and run these tests locally; Python syntax checks alone do not prove Django runtime behavior. SQLite transaction locking is not equivalent to PostgreSQL row-level locking under concurrency.

### Preview
`tracknest_auth_design_preview.html` is an optional static browser preview of the redesigned sign-in/sign-up screen. It has no running database or working login by itself. Use the Django server URL to exercise actual authentication.

---

## Premium TrackNest dashboard (November 2026)

The existing **Sign In** and **Create Account** pages were preserved. Only the signed-in application was redesigned to use a light finance dashboard, fixed navy navigation, four real-data summary cards, Chart.js visualizations and responsive workspace pages.

### Dedicated workspaces

- **Dashboard:** all-time balance, monthly income, expenses and net savings; monthly charts and latest transactions
- **Income / Expenses:** add transactions with date, category, payment method and notes; filter history and edit/delete saved records
- **Transactions:** date range, category, type and description filters; sorting, client-side pagination, edit, view details, delete and CSV export
- **Budgets:** monthly budget plus individual expense-category budgets with progress, creation, editing and deletion
- **Categories:** manage private income and expense categories; historical labels follow a category rename
- **Reports & Analytics:** database-aggregated bar, line and doughnut charts, date filtering, CSV and PDF exports
- **Savings Goals:** create/edit/delete targets and record goal allocations (not cash transfers)
- **Notifications:** persisted 80%, 90%, 100% budget milestones and read/unread controls
- **Settings:** light/dark mode and budget-email preference; currency remains NPR because automatic currency conversion is not implemented
- **My Profile:** update name/phone, change password, request verified email changes

The forecast chart and rule-based financial advisor remain demonstrations and are labelled accordingly. The app cannot stop payments performed outside TrackNest.

### Required database migration

The additive migration `accounts/migrations/0002_premium_finance.py` creates category, category-budget, goal, notification and preference tables, and adds optional transaction notes/payment method fields. It does **not** delete or replace existing users, expenses or budgets.

Run within the existing environment:

```bash
python manage.py migrate --noinput
python manage.py check
python manage.py test accounts --verbosity 2
```

The existing Mac GitHub auto-sync launcher applies migrations when it restarts. Back up `local-data/db.sqlite3` before major changes.

### Development launch

You can use your existing `TrackNest_Auto_Localhost_Mac/START_TRACKNEST.command` launcher. The repository also includes `START_TRACKNEST.command` for launching a local checkout of the source. A standalone GitHub download may need macOS execute permission.

The web app opens at `http://127.0.0.1:8000/`. Leave the Django server running.

### SMTP configuration

Configure Django SMTP environment variables (see `.env.example`), or the existing private macOS file `~/.tracknest/email.json`, before expecting budget alerts in users' inboxes. No credentials belong in GitHub.

Alert notifications are saved to the app database even when SMTP isn't configured. Current signup addresses are **not verified**, so enable email verification before opening public registration. Real delivery also needs a provider with suitable rate limits and retry management.

### Important implementation limits

- The dashboard and Reports totals are aggregated from the user's database records, but the transaction browser currently loads up to 500 recent records; full server-side pagination is a future scalability improvement.
- Budget enforcement and category limits are protected by Django validation. SQLite does not provide the same concurrency guarantees as PostgreSQL row locking for simultaneous requests.
- Goal contributions are recorded as allocations toward a goal, not external transfers or additional expense transactions.
- Currency conversion is not implemented; all financial values are NPR.
- Charts use recorded financial data; the original linear-multiplier forecast is not a trained or validated prediction model.
- GitHub Actions verifies migrations and Django tests. Manual desktop and mobile browser tests are still necessary.

### TrackNest financial assistant

The Financial Advisor page now calls `POST /api/assistant/ask/` with an authenticated JSON body such as `{"message":"How much did I spend this month?"}`. Its reply is calculated on the Django server from the logged-in user's saved transactions, monthly and category budgets, and savings-goal allocations.

The assistant can explain income, expenses, remaining budget, category spending, recent transactions, savings-goal progress and basic saving suggestions. Each response can link to the relevant workspace. It **cannot** create, edit, delete or transfer money, and does not send financial data to third-party AI services.

**Important:** This is a local, rules-based financial insights assistant, **not** a generative large language model. It cannot understand arbitrary complex language or provide personalized regulated financial advice. An optional hosted LLM with consent, privacy safeguards, token budgets and a securely stored API key can be added later if needed. This version requires no API credentials.

Suggested questions: "Show my recent transactions", "What is my remaining monthly budget?", "Where do I spend the most?", "What is my income this month?", and "How are my savings goals going?" The chat history is held only in the visible browser panel and can be cleared without changing records.

Run tests with `python manage.py test accounts.tests_assistant` in the existing virtual environment.

---

## Budget-first onboarding and eSewa TEST checkout (November 2026)

**New registrations:** After creating an account, the user first chooses a monthly expense budget on the Budgets page. Until a limit has been explicitly set, TrackNest rejects new income and expense records and blocks eSewa checkout. The budget can be modified later. Existing saved budget rows are retained and marked configured by the additive migration.

**Expense recording:** TrackNest still supports manually recorded cash, bank, card and wallet expenses. For eSewa testing, an independent *Pay with eSewa Test* button on the Expenses page initiates an eSewa ePay V2 **sandbox merchant** checkout. This is a merchant-payment demonstration, **not** a method for sending funds to arbitrary personal wallets or external billers.

**Payment safety:**
- Only test merchant checkout is supported; there is NO production eSewa URL or live money transfer in this integration.
- The customer is redirected to eSewa's sandbox. Wallet authentication stays with eSewa, never TrackNest.
- A pending checkout temporarily reserves its amount against the current month's and category's limits to reduce double-spending across simultaneous requests.
- The success redirect's signed response is validated with eSewa HMAC-SHA256, then TrackNest independently checks the official eSewa sandbox transaction-status API.
- Only a verified `COMPLETE` status creates one expense transaction. Duplicate callbacks or status checks do not create additional expense entries.
- The expense is marked `eSewa (Sandbox)` and includes an explicit test-only note. **Use a separate test account**: sandbox expenses affect that account's dashboard and budget totals for demonstration.
- Verified eSewa transactions cannot be manually edited/deleted because those records require an auditable payment/reversal workflow.
- Once budget spending reaches 100%, new in-app expenses and eSewa checkouts are blocked, and the existing registered-email threshold alert is requested if real SMTP is configured.
- A completed external payment must still be reconciled and recorded, even if the budget has since been changed. TrackNest cannot recall payments after eSewa has authorized them or prevent transactions initiated independently in another app.

**Enable the sandbox without VS Code (macOS):**

1. Open [official eSewa ePay documentation](https://developer.esewa.com.np/pages/Epay). Find the ePay V2 UAT/sandbox merchant code and test HMAC secret. Never use production merchant credentials in the sandbox.
2. Run `ENABLE_ESEWA_SANDBOX.command` from the project folder. It prompts for test details and stores them in `~/.tracknest/esewa.json` with owner-only file permissions.
3. Restart the existing `START_TRACKNEST.command` auto-sync launcher, open `/budgets/`, and set a small monthly limit in a **test account**.
4. Open `/expenses/`, enter a description, category and amount within the remaining budget, and select **Pay with eSewa Test**.
5. Complete the sandbox checkout, return to TrackNest, and verify that exactly one test expense was recorded. If a redirect is interrupted, use **Check status** on the payment attempt.
6. At 100%, look for an in-app notification and check the registered email inbox (email requires SMTP credentials; the eSewa test key is unrelated to Gmail SMTP).

**Localhost caveat:** eSewa may not accept a plain HTTP localhost callback URL. A public HTTPS development hostname/tunnel may be needed to fully test browser redirects; configure Django's allowed hosts, CSRF origins and secure settings appropriately. An actual end-to-end interaction with the eSewa sandbox has **not** been verified solely by Django's mocked integration tests.

**Production requirements (not implemented):** registered merchant approval, legitimate payable products/services, real production credentials, HTTPS host, robust asynchronous status reconciliation, refunds/chargebacks, provider outages, audit logs, PostgreSQL transactional locking, user email verification, merchant compliance and real payment tests. Do not switch this test code to production by changing URL strings.

**Files added or changed:** `accounts/esewa.py`, `accounts/models.py`, `accounts/migrations/0003_esewa_checkout.py`, `accounts/views.py`, `config/urls.py`, `config/settings.py`, `templates/esewa_checkout.html`, `templates/esewa_result.html`, `templates/index.html`, `accounts/tests_esewa.py`, `ENABLE_ESEWA_SANDBOX.command`, `.env.example`.

Use `python manage.py migrate` and `python manage.py test accounts` in the active virtual environment, or allow the existing Mac auto-sync launcher to apply migrations. Back up the current SQLite database first.
