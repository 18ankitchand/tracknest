# TrackNest — browser-only GitHub → Render setup

## What is included
- Existing TrackNest Django site, authentication and budget API, administrative overview
- `render.yaml` blueprint for a web service and PostgreSQL
- `build.sh` for dependencies, static files and migrations
- `accounts/migrations/0001_initial.py` database schema
- Environment-driven security configuration and `.gitignore`

## Upload to GitHub without VS Code
1. Sign into https://github.com and create a **private** repository named `tracknest`.
2. Extract the downloaded ZIP.
3. Open the **expanse_tracker_django** folder in Finder.
4. In your new GitHub repository, select **Add file > Upload files**.
5. Drag the **contents** of that folder to the upload area (not the ZIP). Confirm `manage.py`, `render.yaml`, `accounts/`, `config/`, `templates/` are present. If folder upload fails, use GitHub's web editor or a browser-based developer workspace.
6. Commit to main. Never upload `.env`, `db.sqlite3`, passwords or keys.

## Deploy via Render Blueprint (browser)
1. Sign into https://dashboard.render.com with GitHub.
2. Select **New > Blueprint**, authorize your private TrackNest repo, choose `render.yaml`, and review resources.
3. Deploy. The blueprint provisions a **free web service** and **free PostgreSQL database**.
4. Check logs for migrations and `collectstatic`, then open the `.onrender.com` URL.
5. Register a dummy account first and test login, budget limits and admin access.

## Critical warnings
- Render free PostgreSQL **expires after 30 days, has no backups**, and is not suitable for actual financial records.
- Render free web service can sleep after inactivity.
- Email backend is **console-only** until a genuine email API provider is integrated. Render free web services block SMTP ports 25/465/587, so ordinary Gmail SMTP alerts will **not** work there.
- Admin superuser needs a separate secure one-time provisioning method. No administrator password is bundled.
- Full Django integration tests were NOT run in the artifact creation environment. Before using real user data, check deployment logs, test flows, configure privacy/security, backups and proper paid durable storage.
- Never place secret keys or database URLs in GitHub repository contents or chat messages.

## Future chat-to-deploy workflow
Connect GitHub to ChatGPT. When an available editing workflow is authorized, changes are made as commits or pull requests and Render redeploys the connected branch. Connecting GitHub **does not alone guarantee** this conversation can push code; available write permissions and tools must be confirmed.
