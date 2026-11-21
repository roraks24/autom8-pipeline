# Autom8 Pipeline 🚀

**Autom8 Pipeline** is an autonomous end-to-end job hunt and application platform built in Python. It discovers matching startup and internship opportunities across platforms (Wellfound and Internshala), tailors dynamic ATS-optimized resumes in real time, automates form filling with human-like pacing, and delivers executive execution summaries directly to WhatsApp.

---

## 🌟 Key Features

- **Automated Multi-Platform Discovery:** Traverses directories and keyword categories across Wellfound and Internshala with multi-page pagination and duplicate filtering.
- **Intelligent Role Classification:** Categorizes roles into prioritized tiers (Tier 1: GenAI Engineer, Tier 2: AI / Backend / Full-Stack Engineer, Tier 3: AI Agent Developer) while eliminating non-engineering positions.
- **Dynamic ATS Resume Tailoring:** Generates customized, ATS-compliant PDF resumes on the fly matching the candidate's verified skills and projects with the employer's specific job description.
- **WAF-Safe Form Automation:** Powered by Playwright with randomized human pacing (15–30s delays), React 18 state-bypass input setters, and automated second-screen dismissal.
- **Automated Dispatch & Reporting:** Logs full audit trails, captures proof screenshots for every application, and automatically dispatches formatted daily status reports to WhatsApp.

---

## 🏗️ Architecture

```
application automat8/
├── src/
│   ├── appliers/               # Multi-platform automation engines
│   │   ├── ats.py              # Ashby, Lever, Greenhouse handlers
│   │   ├── internshala.py      # Internshala REST API & modal applier
│   │   ├── wellfound.py        # Wellfound v2 modal automation engine
│   │   ├── internshala_discovery.py # Live multi-page discovery
│   │   ├── wellfound_discovery.py   # Live directory scanner
│   │   └── router.py           # Master application dispatcher
│   ├── core/
│   │   ├── classifier.py       # Tier 1-3 role classification engine
│   │   ├── tailor.py           # Dynamic ATS resume generator
│   │   └── workflow.py         # Daily workflow execution orchestrator
│   ├── db/
│   │   └── repository.py       # SQLite persistence & priority queries
│   ├── notifications/
│   │   ├── reporter.py         # Markdown & WhatsApp summary generator
│   │   └── whatsapp.py         # WhatsApp Web & Desktop delivery engine
│   └── config.py               # Centralized configuration & settings
├── boards.json                 # Target search slugs and directory categories
├── answer_bank.json            # Candidate profile, answers & standard responses
├── resume_template.html        # ATS-optimized HTML resume template
├── daily_workflow.py           # Master CLI orchestrator (Pipeline v2.0)
└── main.py                     # Unified CLI entry point
```

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/roraks24/autom8-pipeline.git
cd autom8-pipeline
pip install -r requirements.txt
playwright install chromium
```

### 2. Configuration

1. Configure `whatsapp_config.json` (copy from `whatsapp_config.example.json`).
2. Update `answer_bank.json` with your candidate information and custom pitch answers.
3. Place session cookies in `cookies/` using the provided login scripts:
   ```bash
   login_wellfound.bat
   login_internshala.bat
   login_whatsapp.bat
   ```

### 3. Running the Pipeline

- **Live Auto-Submit (Daily Batch):**
  ```bash
  python daily_workflow.py --count 20 --submit
  ```
- **Staging & Review Mode (Pre-fill & screenshot only):**
  ```bash
  python daily_workflow.py --count 20
  ```
- **Check Real-time Pipeline Metrics:**
  ```bash
  python main.py stats
  ```

---

## 📊 Priority Tiers

1. **Tier 1:** GenAI Engineer / Developer (`genai`, `llm`, `rag`, `prompt engineering`)
2. **Tier 2:** AI Engineer / Developer (`applied ai`, `python developer`, `fastapi`, `backend`, `full stack`)
3. **Tier 3:** AI Agent / Agentic AI (`agentic`, `ai agent`, `langgraph`, `crewai`, `autogen`)

---

## 🛡️ License

MIT License. Designed and engineered for personal job search automation.
