# GitHub Stats Failover

A complete Python/FastAPI failover service for GitHub profile statistics cards.

## Guaranteed display chain

```text
Primary third-party card
        |
        | failed
        v
Live Python-generated backup
        |
        | failed
        v
Last repository SVG snapshot
        |
        | missing or damaged
        v
Permanent bundled safety card
```

The endpoint always returns an image. Your GitHub profile statistics section does not disappear.

## Project structure

```text
github-stats-failover/
│
├── api/
│   └── index.py
│
├── services/
│   ├── github_api.py
│   ├── primary_provider.py
│   ├── svg_generator.py
│   └── failover.py
│
├── assets/
│   └── fallback/
│       ├── stats.svg
│       ├── streak.svg
│       └── languages.svg
│
├── scripts/
│   └── generate_snapshots.py
│
├── .github/
│   └── workflows/
│       └── update-stats-snapshots.yml
│
├── .env.example
├── requirements.txt
├── .gitignore
├── README.md
└── vercel.json
```

## What each layer does

### Primary

The API first requests the existing public card services.

### Python backup

When a primary card fails, Python directly collects public GitHub information and creates an SVG.

- Statistics: profile and repository data through the GitHub REST API
- Languages: repository language-byte data through the GitHub REST API
- Streak: public contribution-calendar data from the GitHub profile

The public-data backup works without a token. A token is optional.

### Repository snapshots

The workflow regenerates these files every six hours:

```text
assets/fallback/stats.svg
assets/fallback/streak.svg
assets/fallback/languages.svg
```

If GitHub or the live APIs are temporarily unavailable, the service returns the latest committed snapshot.

### Permanent safety card

The project also generates a basic card in memory if a snapshot is missing or corrupted. The endpoint therefore still returns an SVG.


## Windows timezone dependency

This project uses the IANA timezone name:

```text
Asia/Dhaka
```

Windows normally does not ship the IANA timezone database used by Python's
`zoneinfo` module. The project therefore includes the first-party `tzdata`
package in `requirements.txt`.

After pulling this update, install the corrected requirements:

```powershell
python -m pip install -r requirements.txt
```

A direct repair for an already-created environment is:

```powershell
python -m pip install "tzdata>=2026.3,<2027.0"
```

Verify the timezone before starting the API:

```powershell
python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Dhaka'))"
```

Expected output:

```text
Asia/Dhaka
```

## Local installation

Open PowerShell in the project folder.

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Create a Python virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

Install packages:

```powershell
pip install -r requirements.txt
```

Run:

```powershell
uvicorn api.index:app --reload
```

## Local test URLs

Normal automatic failover:

```text
http://127.0.0.1:8000/api/github-card?type=stats&source=auto
http://127.0.0.1:8000/api/github-card?type=streak&source=auto
http://127.0.0.1:8000/api/github-card?type=languages&source=auto
```

Test the live Python backup directly:

```text
http://127.0.0.1:8000/api/github-card?type=stats&source=backup
http://127.0.0.1:8000/api/github-card?type=streak&source=backup
http://127.0.0.1:8000/api/github-card?type=languages&source=backup
```

Test the saved repository snapshots directly:

```text
http://127.0.0.1:8000/api/github-card?type=stats&source=snapshot
http://127.0.0.1:8000/api/github-card?type=streak&source=snapshot
http://127.0.0.1:8000/api/github-card?type=languages&source=snapshot
```

Inspect the response header:

```text
X-Failover-Source
```

Possible values:

```text
primary
python-backup
repository-snapshot
permanent-safety-card
```

## Generate current snapshots locally

Run:

```powershell
python scripts/generate_snapshots.py
```

This replaces the three bundled SVG snapshots only when live data can be generated successfully. Existing snapshot files are preserved when a refresh fails.

## Push to GitHub

```powershell
git init
git add .
git commit -m "Build complete GitHub stats failover service"
git branch -M main
git remote add origin https://github.com/RR0327/github-stats-failover.git
git push -u origin main
```

## Enable the scheduled snapshot workflow

Open the repository:

```text
Actions -> Update GitHub Stats Snapshots -> Run workflow
```

The workflow also runs automatically every six hours.

The workflow has `contents: write` permission so it can commit refreshed SVG files.

### Optional GitHub token

The workflow and local backup work with public information when no token is supplied.

For a higher API rate limit:

1. Create an appropriate fine-grained personal access token.
2. Open the failover repository.
3. Go to `Settings -> Secrets and variables -> Actions`.
4. Create the repository secret:

```text
GH_STATS_TOKEN
```

Never commit the token in `.env`, source code, or the README.

## Deploy to Vercel

1. Import this GitHub repository into Vercel.
2. Open `Settings -> Environment Variables`.
3. Add every variable from `.env.example`.
4. `GITHUB_TOKEN` may remain empty for public data.
5. Deploy the project.

Vercel detects the FastAPI `app` object in `api/index.py`. The `vercel.json` file includes the committed SVG snapshot assets in the function bundle.

## Deployed tests

Replace `YOUR-DOMAIN` with the Vercel domain.

```text
https://YOUR-DOMAIN.vercel.app/api/github-card?type=stats&source=auto
https://YOUR-DOMAIN.vercel.app/api/github-card?type=stats&source=backup
https://YOUR-DOMAIN.vercel.app/api/github-card?type=stats&source=snapshot
```

Repeat with:

```text
type=streak
type=languages
```

## GitHub profile README section

Replace `YOUR-DOMAIN` with the deployed Vercel domain.

```html
## GitHub Stats

<table align="center">
  <tr>
    <td align="center">
      <img
        src="https://YOUR-DOMAIN.vercel.app/api/github-card?type=stats&source=auto"
        alt="GitHub Stats"
      />
    </td>
    <td align="center">
      <img
        src="https://YOUR-DOMAIN.vercel.app/api/github-card?type=streak&source=auto"
        alt="GitHub Streak"
      />
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <img
        src="https://YOUR-DOMAIN.vercel.app/api/github-card?type=languages&source=auto"
        alt="Top Languages"
      />
    </td>
  </tr>
</table>
```

## Operational behavior

```text
Primary works:
    primary card is displayed

Primary fails:
    live Python-generated card is displayed

Primary and live GitHub data fail:
    last committed SVG snapshot is displayed

Snapshot is unexpectedly missing:
    permanent safety SVG is displayed
```

No normal execution path returns a broken image response.
