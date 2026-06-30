<a id="readme-top"></a>

<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

<h3 align="center">Polymarket Forecaster</h3>

  <p align="center">
    A paper-trading research tool that forecasts political prediction markets with an LLM, scores itself against the crowd price, and serves the results as a live dashboard.
    <br />
    <a href="https://github.com/teddycitrus/polymarket"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/teddycitrus/polymarket">View Demo</a>
    &middot;
    <a href="https://github.com/teddycitrus/polymarket/issues">Report Bug</a>
    &middot;
    <a href="https://github.com/teddycitrus/polymarket/issues">Request Feature</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul><li><a href="#built-with">Built With</a></li></ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#architecture">Architecture</a></li>
    <li><a href="#security">Security</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
  </ol>
</details>

## About The Project

Polymarket prices are already a crowd-sourced probability forecast, and they are usually decent. This project is only useful if it can systematically disagree with the crowd and be right more often. So it does not try to "predict the outcome"; it tries to beat a price.

For a given political market it pulls the live crowd price, gathers recent dated news with web search, runs an ensemble of LLM forecasts using a strict five-step reasoning prompt, and stores the result. When markets resolve it records the outcome and computes Brier scores for both the model and the crowd. The difference is the net edge: positive means the model is beating the market, negative means it is not. The honest part is built in; with zero resolved markets the dashboard says the edge is unknowable, and it stays noisy until roughly fifty markets have settled.

Key capabilities:

* Live ingestion of political markets from the Polymarket Gamma API and real-time prices from the CLOB order book.
* LLM ensemble forecasting with a five-step decompose-and-estimate prompt, three runs averaged per market, grounded in dated web-search news.
* Append-only, timestamped storage in libSQL so you can track how both your estimate and the crowd price drift over time.
* Automated resolution tracking and Brier scoring, model versus crowd, surfaced as a cumulative net-edge trend.
* A serverless deployment on Vercel with a read-only JSON metrics endpoint and a token-protected forecast endpoint, fronted by a single-file dashboard.
* A local-first workflow: a nightly job, a morning board, and a calibration report that all run from the command line.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

[![Python][Python-badge]][Python-url]
[![Anthropic][Anthropic-badge]][Anthropic-url]
[![Turso][Turso-badge]][Turso-url]
[![Vercel][Vercel-badge]][Vercel-url]
[![SQLite][SQLite-badge]][SQLite-url]

| Layer | Tools |
| --- | --- |
| Forecasting | Anthropic Claude (Sonnet) via the official Python SDK, server-side web search |
| Data | Polymarket Gamma API, Polymarket CLOB API |
| Storage | libSQL via libsql-client; Turso in the cloud, local SQLite file otherwise |
| API | Vercel Python serverless functions (`@vercel/python`) |
| Frontend | Static HTML, vanilla JavaScript, inline SVG |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

The project runs locally with no cloud accounts; the database falls back to a local SQLite file and forecasting uses your Anthropic key. Turso and Vercel are only needed for the hosted deployment.

### Prerequisites

* Python 3.12 or newer.
* An Anthropic API key.
* For local web emulation or deployment: Node.js and the Vercel CLI (`npm install -g vercel`).
* For the hosted database: a Turso account (free tier is sufficient).

### Installation

1. Clone the repo.
   ```sh
   git clone https://github.com/teddycitrus/polymarket.git
   cd polymarket
   ```
2. Install dependencies.
   ```sh
   pip install -r requirements.txt
   ```
3. Configure environment variables.
   ```sh
   cp .env.example .env
   # then edit .env and set ANTHROPIC_API_KEY (and the others if deploying)
   ```
4. Run a forecast against a single live market.
   ```sh
   python scripts/run-forecasts.py --slug will-gavin-newsom-win-the-2028-democratic-presidential-nomination-568
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

**Command-line scripts**

| Command | What it does |
| --- | --- |
| `scripts/list_markets.py` | List live binary political markets and their crowd prices. |
| `scripts/run-forecasts.py --slug <slug>` | Forecast one market end to end and print the edge summary. |
| `scripts/batch-forecasts.py --limit N` | Forecast a batch of liquid mid-priced markets (crowd price between 0.10 and 0.90). |
| `scripts/resolve-markets.py` | Record outcomes for any tracked markets that have settled. |
| `scripts/generate-report.py` | Print the calibration report: model Brier, market Brier, and net edge. |
| `scripts/morning.py` | The morning board: open markets ranked by model-versus-crowd disagreement. |
| `scripts/nightly.py --limit N` | Unattended run: resolve, batch-forecast, then write a dated digest. |
| `scripts/devserver.py` | Local emulation of the Vercel deployment at http://localhost:3000. |

**HTTP API**

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/dashboard` | none | Calibration metrics, open markets, and resolved history as JSON. |
| POST | `/api/forecast` | Bearer token | Run a small batch forecast. Body: `{"limit": 1, "low": 0.10, "high": 0.90}`. |

```sh
# Read the metrics the dashboard renders.
curl https://your-app.vercel.app/api/dashboard

# Trigger a forecast (token is your FORECAST_API_TOKEN).
curl -X POST https://your-app.vercel.app/api/forecast \
  -H "Authorization: Bearer $FORECAST_API_TOKEN" \
  -d '{"limit": 1}'
```

**Scheduling**

On Windows the nightly job is intended to run from Task Scheduler so the digest is ready each morning. The forecasting work happens locally and writes to the shared database; the dashboard reads from it.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Architecture

```
src/
  llm.py               Anthropic SDK wrapper (web search + text generation)
  ingest/polymarket.py Gamma markets and events, CLOB live prices
  retrieve/news.py     Dated news via web search
  forecast/            Five-step prompt and the ensemble runner
  score/               libSQL persistence and Brier scoring
  pipeline.py          The shared single-market engine
api/
  dashboard.py         GET read-only metrics
  forecast.py          POST token-protected batch forecast
public/                index.html and app.js (the dashboard)
scripts/               CLI tools and the local dev server
vercel.json            Routing, runtime pinning, function limits, security headers
```

The database layer routes to Turso when `TURSO_DATABASE_URL` is set and to a local SQLite file otherwise, using the same libSQL code path in both cases. The forecast endpoint defers its heavy imports until after the auth check so unauthorized requests stay cheap.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Security

The project was hardened against the OWASP Top 10 where it applies. Highlights:

* The write endpoint requires a Bearer token, compared in constant time, with a minimum length enforced and a fail-closed default.
* Inputs are validated and clamped; request bodies are size-capped; errors return generic messages while detail is logged server-side only.
* Outbound identifiers are validated against allowlists before they touch a URL, which prevents path traversal and request splitting.
* Security headers (HSTS, CSP, frame options, nosniff, referrer policy) are set in `vercel.json`, and the dashboard JavaScript is served from a file so a strict CSP applies.
* Secrets live only in environment variables and are kept out of version control; dependencies are pinned.

Application-level rate limiting is intentionally left to the platform (Vercel Firewall) since serverless functions are stateless; the strong token plus clamped batch size bound abuse in the meantime.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [x] Single-market forecast pipeline with crowd-price comparison
- [x] Batch forecasting, resolution tracking, and Brier scoring
- [x] Local nightly job, morning board, and calibration report
- [x] Serverless migration to Vercel with Turso storage
- [x] Security hardening pass
- [ ] Accumulate fifty or more resolved markets for a meaningful net edge
- [ ] Cloud cron for hands-off forecasting on Vercel Pro
- [ ] Local-to-Turso data migration script
- [ ] Additional market categories such as sports and crypto

See the [open issues](https://github.com/teddycitrus/polymarket/issues) for the full list.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contributing

Contributions are what make the open source community such an amazing place to learn and create. Any contributions you make are greatly appreciated.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Contact

Project Link: [https://github.com/teddycitrus/polymarket](https://github.com/teddycitrus/polymarket)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/teddycitrus/polymarket.svg?style=for-the-badge
[contributors-url]: https://github.com/teddycitrus/polymarket/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/teddycitrus/polymarket.svg?style=for-the-badge
[forks-url]: https://github.com/teddycitrus/polymarket/network/members
[stars-shield]: https://img.shields.io/github/stars/teddycitrus/polymarket.svg?style=for-the-badge
[stars-url]: https://github.com/teddycitrus/polymarket/stargazers
[issues-shield]: https://img.shields.io/github/issues/teddycitrus/polymarket.svg?style=for-the-badge
[issues-url]: https://github.com/teddycitrus/polymarket/issues
[license-shield]: https://img.shields.io/github/license/teddycitrus/polymarket.svg?style=for-the-badge
[license-url]: https://github.com/teddycitrus/polymarket/blob/main/LICENSE
[Python-badge]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
[Anthropic-badge]: https://img.shields.io/badge/Anthropic_Claude-191919?style=for-the-badge&logo=anthropic&logoColor=white
[Anthropic-url]: https://www.anthropic.com/
[Turso-badge]: https://img.shields.io/badge/Turso-4FF8D2?style=for-the-badge&logo=turso&logoColor=black
[Turso-url]: https://turso.tech/
[Vercel-badge]: https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white
[Vercel-url]: https://vercel.com/
[SQLite-badge]: https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white
[SQLite-url]: https://www.sqlite.org/
