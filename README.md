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
