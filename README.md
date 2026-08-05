# Old Pro CRM — Cold Call Tracker

A full production CRM built for **Old Pro Construction Services** (Etobicoke, ON) by directing Claude AI through architecture, debugging, testing, and deployment — zero manual coding.

Built to manage cold calling campaigns targeting real estate agents, property managers, landlords, and condo owners across the GTA.

---

## Features

### Desktop App (PyQt6)
- Dark UI with lead list, detail panel, and AI assistant panel
- Persistent SQLite database — all data stays local
- Lead lists: Leads / Follow-Up / Warm / Won / Dead
- Priority system (High/Normal/Low) with color coding
- **Green rows** for leads already called — never lose your place
- Scrollable notes with full call history per lead
- Calendar date picker for follow-up dates
- Call count tracking per lead

### Web Scraping
- **Real estate agents** — realtor.ca public API
- **Property managers** — Yellow Pages Canada + DuckDuckGo HTML search
- **Landlords** — Kijiji listings
- **Condo owners** — Kijiji `__NEXT_DATA__` JSON parsing, private owners only
- Duplicate detection by phone number and address

### Selenium Phone Extraction
- Headless Firefox clicks Kijiji's "Reveal Phone" button automatically
- Extracts and saves phone numbers to leads without manual intervention
- Uses Firefox session cookies for authenticated access
- Marks leads "N/A" when no phone is available — no repeat attempts

### AI Integration (OpenRouter)
- **Call Opener** — personalized cold call script for each lead, written for text-to-speech
- **Follow-Up SMS** — under 160 characters, ready to send
- **Qualify Lead** — AI reads the lead and recommends pitch angle
- **Enrich / Extract** — paste company info, AI extracts phone/email/priority
- **Business Card Reader** — photo a card, AI fills in contact details via vision API

### Text-to-Speech
- Google TTS (`gTTS`) + `ffplay` reads call scripts aloud
- Speed calibrated to 1.2x for natural pacing
- Speak / Stop buttons in the AI panel

### TextNow Integration
- **📱 Call via TextNow** button copies number to clipboard and opens TextNow web
- Called leads turn green automatically
- Previous lead turns green when you move to the next

### Mobile Web App (Flask)
- Responsive mobile-first UI served via Flask
- Accessible from phone via ngrok tunnel from anywhere
- Same SQLite database — changes sync instantly both ways
- Log calls, move leads, view notes, tap phone number to dial
- Auto-refreshes every 30 seconds

### Lead Management
- Import individual Kijiji listings by URL — auto-extracts phone
- Deduplication engine — merges by phone/address, preserves notes
- Photo attachments — thumbnail in detail panel, double-click for full size
- Merge logic on import — fills missing fields, appends notes, never overwrites

### Reminders
- Follow-up due badges — orange rows, count in sidebar
- Scrape reminder — green/orange/red indicator showing days since last scrape
- Auto follow-up dates: "Call back in 8/14/30 days" sets date automatically

---

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop UI | Python · PyQt6 |
| Mobile UI | Flask · HTML/CSS/JS |
| Database | SQLite |
| Scraping | requests · BeautifulSoup · Kijiji `__NEXT_DATA__` JSON |
| Automation | Selenium · Firefox (geckodriver) |
| AI | OpenRouter API (GPT, Gemini, Mistral) |
| TTS | gTTS · ffplay (ffmpeg) |
| Tunnel | ngrok |
| Auth | browser-cookie3 (Firefox session cookies) |

---

## Setup

```bash
# Install dependencies
pip install PyQt6 requests beautifulsoup4 flask selenium \
            browser-cookie3 gtts qrcode --break-system-packages

# Firefox driver
sudo apt install firefox-geckodriver

# Run desktop app
python3 old_pro_crmWithAutoSpeak.py

# Run mobile web server (separate terminal)
python3 old_pro_web.py

# Expose via ngrok (separate terminal)
ngrok http 5000
```

### API Key
Paste your [OpenRouter](https://openrouter.ai) API key in the sidebar of the desktop app and click **Save Key**. Stored locally in `~/.old_pro_crm_settings.json`.

---

## Files

| File | Description |
|---|---|
| `old_pro_crmWithAutoSpeak.py` | Main desktop CRM application |
| `old_pro_web.py` | Flask mobile web server |
| `start.sh` | Launch script — starts web server, ngrok, and desktop app |
| `stop.sh` | Stop all running processes |

---

## Data Storage

| Path | Contents |
|---|---|
| `~/.old_pro_crm.db` | SQLite database — all leads, call logs, notes |
| `~/.old_pro_crm_settings.json` | API key, last scrape date |
| `~/.old_pro_crm_images/` | Lead photo attachments |

---

## Built With AI

This entire application was built by directing Claude AI — no manual coding. The human role was:
- Product decisions and feature requirements
- Testing and QA
- Debugging direction
- Deployment and integration

This project demonstrates **AI-assisted software development** as a production workflow.

---

## Author

**Christo (Jo) Bakas** — Toronto, ON  
Senior Technical Writer · IT Specialist · AI-Assisted Developer  
[Technical Writing Samples](https://github.com/chris007-s/technical-writing-samples)
