# Autom8 Pipeline 🚀

**Autom8 Pipeline** is an autonomous end-to-end job discovery, ATS resume tailoring, and application automation platform for **Internshala** and **Wellfound**. It stores all submitted applications in a **single JSON database** (`data/applied_jobs.json`), captures **zero screenshots**, and runs from a unified entrypoint (`run.py`).

---

## 🏗️ Architecture

```
application automat8/
├── run.py                          # Single unified CLI entrypoint for the whole pipeline
├── README.md
├── requirements.txt
├── .env.example                    # Groq API key & model template (copy to .env)
├── config/                         # Candidate answers, boards, resume template & configs
│   ├── answer_bank.json            # Candidate profile, bio & standard form responses
│   ├── boards.json                 # Target Wellfound directories & Internshala feeds
│   ├── excluded.txt                # Manually excluded companies
│   ├── master_resume.pdf           # Master CV reference
│   ├── master_resume.txt           # Master CV text reference
│   ├── resume_template.html        # ATS-optimized HTML Jinja2 resume template
│   ├── whatsapp_config.example.json
│   └── whatsapp_config.json        # WhatsApp target phone & optional CallMeBot key
├── cookies/                        # Platform authentication cookies
│   ├── internshala_cookies.json
│   └── wellfound_cookies.json
├── data/                           # JSON-only Persistence (No SQLite, No PNGs, No .md logs)
│   ├── applied_jobs.json           # SINGLE database for all applied jobs + synced outcomes
│   └── skipped_cache.json          # Exclusion cache (expired, unpaid, ineligible, rejected)
├── tailored_resumes/               # Generated per-job ATS PDF resumes
└── src/                            # Formatted modular pipeline package
    ├── config.py                   # Paths, .env loader, candidate defaults & compliance policies
    ├── workflow.py                 # End-to-end daily orchestrator
    ├── storage/
    │   └── applied_store.py        # AppliedJobsStore & SkippedCacheStore (atomic JSON)
    ├── core/
    │   ├── browser.py              # Shared Playwright Chrome/Chromium context helpers
    │   ├── classifier.py           # Tier 1-3 + relevance scoring + YoE/stack/unpaid filters
    │   ├── llm.py                  # Groq JD-grounded pitch, screening answers & salary align
    │   └── tailor.py               # Dynamic ATS resume tailoring & PDF compilation
    ├── discovery/
    │   ├── internshala.py          # Fresher jobs, internship categories & keyword feeds
    │   └── wellfound.py            # Multi-page Wellfound directory scanner
    ├── appliers/
    │   ├── ats.py                  # Ashby, Lever & Greenhouse form handlers
    │   ├── internshala.py          # Internshala REST API applier + pre-submit checks
    │   ├── wellfound.py            # Wellfound v2 React modal automation engine
    │   └── router.py               # Master dispatcher (routes, persists to JSON, 0 PNGs)
    ├── notifications/
    │   ├── reporter.py             # Console & WhatsApp summary formatting
    │   └── whatsapp.py             # CallMeBot / WhatsApp Web / Desktop URI dispatcher
    └── outreach/
        └── linkedin.py             # Account-safe LinkedIn recruiter note generator
```

### Module Dependency Flow

`run.py` → `src/workflow.py` → `{discovery, appliers, notifications, outreach}` → `{core, storage}` → `config.py`

---

## 🚀 Usage (`run.py`)

### Run Full Daily Pipeline
```bash
# Live auto-submit to fulfill daily quota (20 Internshala + 20 Wellfound = 40 total)
python run.py

# Target one platform or custom count
python run.py --platform wellfound --count 10
python run.py --platform internshala --count 20

# Stage & pre-fill only (no final submit click)
python run.py --stage

# Apply N additional roles ignoring today's already-submitted count
python run.py --force --count 5
```

### Pipeline Utilities
```bash
# View real-time metrics from data/applied_jobs.json & data/skipped_cache.json
python run.py stats

# Inspect recent applied jobs (defaults to today's date)
python run.py history --date 2026-11-24 --limit 40

# Preview fresh paid, eligible jobs without applying
python run.py discover --platform internshala --limit 10

# Apply directly to a single URL
python run.py apply --url "<JOB_URL>" --company "Acme" --title "AI Engineer"

# Generate an ATS-tailored PDF resume
python run.py tailor --company "Acme" --title "GenAI Engineer" --jd "FastAPI LangGraph RAG"

# Generate LinkedIn recruiter outreach notes from applied_jobs.json
python run.py outreach --limit 15

# Run pipeline and automatically generate top Tier 1/3 outreach queue
python run.py --with-outreach

# Sync live Internshala application outcomes (Seen / In-touch / Not Selected) into data/applied_jobs.json
python run.py sync --pages 5

# One-time interactive session login
python run.py login wellfound
python run.py login internshala
python run.py login whatsapp
```

### Environment Configuration (`.env`)
Copy `.env.example` to `.env` and set `GROQ_API_KEY` (and optional `GROQ_MODEL`, default `openai/gpt-oss-20b`) to enable JD-grounded 3-sentence pitches, dynamic screening question answering, Wellfound React-Select resolution, and tailored ATS summaries grounded strictly in `config/master_resume.txt`.

---

## 🛡️ Policy Enforcement

- **Single Applied Database (JSON-Only):** Every submitted job is written atomically to `data/applied_jobs.json` — zero SQLite, zero `.md` report files, and zero screenshots stored on disk.
- **Strict Zero-Unpaid Policy:** Automatically excludes unpaid, volunteer, equity-only, or zero-stipend listings across discovery, modal inspection, and pre-submit checks.
- **Human-Like Pacing:** Randomized 15–30s intervals between live submissions protect candidate accounts from WAF triggers.
