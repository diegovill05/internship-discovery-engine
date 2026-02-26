# Internship Discovery Engine

A tool to discover and track internship opportunities.

## Setup

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install the package in development mode
pip install -e ".[dev]"

# Copy the example env file and fill in your values
cp .env.example .env
```

## Search Providers

The engine supports two search providers. **Brave Search** is the default.

### Brave Search (default)

Get an API key at <https://brave.com/search/api/> and set it in your `.env`:

```
IE_BRAVE_API_KEY=your-brave-api-key-here
```

Or inject it via **GitHub Actions secrets** — add `IE_BRAVE_API_KEY` under
**Settings → Secrets and variables → Actions**. The application reads it
purely from the environment, so no code changes are needed for CI.

### Google Custom Search (alternative)

Create a Programmable Search Engine at
<https://programmablesearchengine.google.com> and generate an API key at
<https://console.cloud.google.com/apis/credentials>.

```
IE_GOOGLE_API_KEY=your-google-api-key-here
IE_GOOGLE_CSE_ID=your-custom-search-engine-id-here
```

Select the provider at runtime with `--source`:

```bash
internship-engine run --source brave   # default
internship-engine run --source google
```

## Usage

```bash
# List recognised categories
internship-engine list-categories

# Run a search (Brave is default)
internship-engine run --location "New York, NY" --track swe

# Use Google instead, with extra options
internship-engine run --source google --keyword Python --max-results 20

# Filter by recency and exclude remote postings
internship-engine run --posted-within-days 7 --no-remote

# Interactive wizard
internship-engine menu
```

## Track Filtering

Filter postings to a specific domain so only relevant roles appear:

| Track | Targets |
|---|---|
| `swe` | Software engineers, web/mobile developers, DevOps |
| `cyber` | Cybersecurity, SOC analysts, security engineers |
| `it` | Help desk, desktop support, IT support, sysadmins |
| `data` | Data analysts, data scientists, ML engineers, BI |
| `all` | No filtering — all postings returned (default) |

```bash
internship-engine run --track swe
internship-engine run --track cyber --location "Austin, TX"
```

When `--track` is set and no `--keyword` is given, optimised query strings
are injected automatically for higher-quality results.

## Active-Posting Check

Skip postings whose page shows a "closed" signal (HTTP 404/410, or phrases
like "position has been filled", "no longer accepting applications", etc.).

```bash
# Drop confirmed-closed postings; keep unknown-status (default)
internship-engine run --track swe --only-active

# Drop both closed AND pages that couldn't be checked (403, timeout)
internship-engine run --track swe --only-active --drop-unknown-active

# Limit network checks to 5 per run (default: 10)
internship-engine run --only-active --active-check-max 5
```

> Pages blocked (403) or rate-limited (429) return `UNKNOWN`, not `INACTIVE`,
> to avoid false positives.

## Interactive Menu

```bash
internship-engine menu
```

Guided prompts for location, track, keywords, source, max results, export
destination, and active-check preference — then runs the same pipeline as
`run`.

## Google Sheets Export

After a run, matched postings can be appended to a master Google Sheet.
Duplicate rows are skipped automatically using a stable hash of title + company
+ URL so re-running the pipeline never creates duplicates.

### Required secrets

| Secret / env var | Description |
|---|---|
| `IE_SHEET_ID` | The Google Sheet ID (the long string in the sheet URL) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of a service-account JSON key file |

> **Note:** `GOOGLE_SERVICE_ACCOUNT_JSON` intentionally has **no** `IE_` prefix
> so it matches the standard GitHub Actions secret naming convention.

### Optional settings

| Variable | Default | Description |
|---|---|---|
| `IE_SHEET_TAB` | `Postings` | Worksheet tab name to write postings into |

### Setup

1. Create a [Google service account](https://console.cloud.google.com/iam-admin/serviceaccounts)
   and download a JSON key file.
2. Share your Google Sheet with the service account email (Editor access).
3. Set the secrets in GitHub Actions under
   **Settings → Secrets and variables → Actions**.

### CLI usage

```bash
# Export to Sheets (uses IE_SHEET_ID from env)
internship-engine run --export sheets

# Override the sheet ID at runtime
internship-engine run --export sheets --sheet-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms

# Write into a different tab
internship-engine run --export sheets --sheet-tab Summer2025
```

### GitHub Actions example

```yaml
- name: Run internship discovery
  env:
    IE_BRAVE_API_KEY: ${{ secrets.IE_BRAVE_API_KEY }}
    IE_SHEET_ID: ${{ secrets.IE_SHEET_ID }}
    GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
  run: internship-engine run --export sheets
```

### Sheet columns

`Added At` | `Category` | `Title` | `Company` | `Location` |
`Date Posted` | `Date Confidence` | `Apply URL` | `Posting URL` |
`Source` | `Hash` | `Status` | `Status Reason` | `Track Match`

Existing sheets with the 11-column legacy format are **auto-migrated** —
the three new columns are appended to the header automatically.

## Testing

```bash
pytest
```
