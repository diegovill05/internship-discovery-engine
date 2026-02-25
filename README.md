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
internship-engine run --location "New York, NY" --category software

# Use Google instead, with extra options
internship-engine run --source google --keyword Python --max-results 20

# Filter by recency and exclude remote postings
internship-engine run --posted-within-days 7 --no-remote
```

## Testing

```bash
pytest
```
