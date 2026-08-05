#!/usr/bin/env python3
"""
Old Pro Construction Services — Cold Call CRM
Scrapes real estate agents and property managers from realtor.ca and Google Maps.
Tracks leads, follow-ups, and call notes in a local SQLite database.
"""

import sys
import sqlite3
import json
import re
import time
import threading
import webbrowser
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton, QLineEdit,
    QLabel, QComboBox, QTextEdit, QDialog, QFormLayout, QDialogButtonBox,
    QHeaderView, QSplitter, QFrame, QMessageBox, QProgressBar,
    QStatusBar, QToolButton, QMenu, QCheckBox, QSpinBox
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSortFilterProxyModel,
    QAbstractTableModel, QModelIndex, QDate
)
from PyQt6.QtWidgets import QDateEdit
from PyQt6.QtGui import QColor, QFont, QIcon, QAction, QPalette

# ─── Database ────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".old_pro_crm.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            company     TEXT,
            phone       TEXT,
            email       TEXT,
            type        TEXT DEFAULT 'Agent',        -- Agent | Property Mgr | Landlord | Staging | Other
            area        TEXT,
            source      TEXT,                        -- how we found them
            list        TEXT DEFAULT 'Leads',        -- Leads | Follow-Up | Warm | Won | Dead
            priority    TEXT DEFAULT 'Normal',       -- High | Normal | Low
            notes       TEXT DEFAULT '',
            added       TEXT DEFAULT (date('now')),
            last_contact TEXT,
            next_followup TEXT,
            call_count  INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS call_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id     INTEGER REFERENCES leads(id) ON DELETE CASCADE,
            called_at   TEXT DEFAULT (datetime('now')),
            outcome     TEXT,   -- Answered | VM Left | No Answer | Callback | Not Interested | Job Booked
            notes       TEXT
        );
        """)

# ─── AI / OpenRouter ─────────────────────────────────────────────────────────

SETTINGS_PATH = Path.home() / ".old_pro_crm_settings.json"
IMAGES_PATH   = Path.home() / ".old_pro_crm_images"
IMAGES_PATH.mkdir(exist_ok=True)

def load_settings():
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}

def save_settings(data):
    s = load_settings()
    s.update(data)
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))

def get_api_key():
    return load_settings().get("openrouter_key", "")


class AIWorker(QThread):
    result  = pyqtSignal(str)
    error   = pyqtSignal(str)

    def __init__(self, task, lead, extra=""):
        super().__init__()
        self.task  = task
        self.lead  = dict(lead)
        self.extra = extra

    def run(self):
        key = get_api_key()
        if not key:
            self.error.emit("No OpenRouter API key saved. Paste your key in the AI panel and hit Save.")
            return
        try:
            prompt = self._build_prompt()
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://oldproconstructionservices.com",
                    "X-Title": "Old Pro CRM",
                },
                json={
                    "model": "openai/gpt-oss-20b:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            data = resp.json()
            if "error" in data:
                self.error.emit(f"API error: {data['error'].get('message', str(data['error']))}")
                return
            raw = data["choices"][0]["message"].get("content")
            if not raw:
                self.error.emit("Model returned empty response. Hit Run again.")
                return
            text = raw.strip()
            if not text:
                self.error.emit("Model returned blank text. Hit Run again.")
                return
            self.result.emit(text)
        except Exception as e:
            self.error.emit(str(e))

    def _build_prompt(self):
        l = self.lead
        name    = l.get("name", "")
        company = l.get("company", "") or name
        phone   = l.get("phone", "")
        type_   = l.get("type", "")
        area    = l.get("area", "GTA")
        notes   = l.get("notes", "")
        calls   = l.get("call_count", 0)

        base = (
            f"You are helping Jo, owner of Old Pro Construction Services in Etobicoke, Ontario. "
            f"Old Pro does patch & paint, drywall, carpentry, trim, kitchen & bath repairs for the GTA. "
            f"Jo is cold calling to get renovation and repair work.\n\n"
            f"Lead: {name} | Company: {company} | Type: {type_} | Area: {area} | "
            f"Phone: {phone} | Calls made: {calls} | Notes: {notes or 'none'}\n"
        )

        if self.task == "opener":
            return (
                base +
                f"\nWrite a SHORT cold call opener to be READ ALOUD by text-to-speech. "
                f"Use commas generously for natural pauses. "
                f"Use ellipses (...) for longer pauses between thoughts. "
                f"Never use dashes or hyphens. Write how a real person speaks on the phone. "
                f"Under 20 seconds spoken. No bullet points. "
                f"Mention Old Pro Construction Services does patch and paint, drywall, and carpentry in {area}. "
                f"End with one simple open question. "
                f"Rhythm example: Hi, is this the property manager? ... My name is Jo, "
                f"and I run Old Pro Construction Services, out of Etobicoke. "
                f"We do patch and paint, drywall, and carpentry across the GTA, "
                f"fast turnarounds, fair prices. ... Do you have a go-to contractor for that?"
            )
        elif self.task == "followup":
            return (
                base +
                f"\nJo already called this lead. Write a SHORT follow-up text message (SMS). "
                f"Under 160 characters. Friendly, no pressure. Mention Old Pro Construction, "
                f"offer a free estimate. Sign off as Jo."
            )
        elif self.task == "qualify":
            return (
                base +
                f"\nExtra context: {self.extra}\n\n"
                f"In 2-3 sentences, tell Jo: is this a good lead for renovation/repair work? "
                f"What is the best angle to pitch them? What service fits them most? Be direct."
            )
        elif self.task == "enrich":
            return (
                base +
                f"\nExtra info provided: {self.extra}\n\n"
                f"Extract from the above any: phone number, email, priority (High/Normal/Low), "
                f"and a one-line note about what kind of work they likely need. "
                f"Reply in this exact format:\n"
                f"Phone: ...\nEmail: ...\nPriority: ...\nNote: ..."
            )
        return base + "\nSummarize this lead in one sentence."


class ImportURLWorker(QThread):
    """Fetch a Kijiji ad URL and extract lead info."""
    found  = pyqtSignal(dict)   # lead data dict
    error  = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            import browser_cookie3, re, json as _json
            cookies     = browser_cookie3.firefox(domain_name=".kijiji.ca")
            cookie_dict = {c.name: c.value for c in cookies}

            # Get ad ID from URL
            ad_id_match = re.search(r"/(\d{7,12})(?:[/?]|$)", self.url)
            if not ad_id_match:
                self.error.emit("Could not find ad ID in URL")
                return
            ad_id = ad_id_match.group(1)

            # Fetch main ad page for title/address/description
            r = requests.get(self.url, headers=HEADERS, cookies=cookie_dict, timeout=15)
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text)

            title   = ""
            address = ""
            desc    = ""
            if match:
                data   = _json.loads(match.group(1))
                apollo = data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__", {})
                ad_key = f"RealEstateListing:{ad_id}"
                if ad_key in apollo:
                    ad      = apollo[ad_key]
                    title   = ad.get("title", "")
                    desc    = ad.get("description", "")
                    loc     = ad.get("location", {})
                    address = loc.get("address", "")

            # Fetch phone via reveal endpoint
            phone = ""
            reveal_url = f"https://www.kijiji.ca/v-get-phone-number/{ad_id}"
            r2 = requests.get(reveal_url, headers=HEADERS, cookies=cookie_dict, timeout=15)
            phones = re.findall(r"\+?1?[\s\.\-]?\(?\d{3}\)?[\s\.\-]\d{3}[\s\.\-]\d{4}", r2.text)
            if phones:
                raw = re.sub(r"\D", "", phones[0])
                if len(raw) >= 10:
                    d     = raw[-10:]
                    phone = f"({d[:3]}) {d[3:6]}-{d[6:]}"

            self.found.emit({
                "name":    ("Condo Owner - " + title[:50]) if title else "Condo Owner - " + ad_id,
                "company": "",
                "phone":   phone,
                "email":   "",
                "type":    "Condo Owner",
                "area":    "Toronto",
                "source":  "Kijiji URL import",
                "notes":   "Kijiji: " + self.url + ("\nAddress: " + address if address else "") + ("\n" + desc[:200] if desc else ""),
            })
        except Exception as e:
            self.error.emit(str(e))



class CardReaderWorker(QThread):
    found = pyqtSignal(dict, int)
    error = pyqtSignal(str)

    def __init__(self, image_path, lead_id, api_key):
        super().__init__()
        self.image_path = image_path
        self.lead_id    = lead_id
        self.api_key    = api_key

    def run(self):
        try:
            import base64, json as _json, re as _re
            with open(self.image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            ext = Path(self.image_path).suffix.lower()
            media_type = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
            }.get(ext, "image/jpeg")
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://oldproconstructionservices.com",
                },
                json={
                    "model": "google/gemma-4-31b-it:free",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:" + media_type + ";base64," + image_data}
                            },
                            {
                                "type": "text",
                                "text": (
                                    "This is a business card. Extract all contact information. "
                                    "Reply ONLY with a JSON object with these fields (empty string if not found): "
                                    "name, company, phone, email, address, title, website. "
                                    "No markdown, no explanation, just the JSON."
                                )
                            }
                        ]
                    }],
                    "max_tokens": 300,
                },
                timeout=30,
            )
            data = resp.json()
            if "error" in data:
                self.error.emit(data["error"].get("message", "API error"))
                return
            text = data["choices"][0]["message"]["content"].strip()
            text = _re.sub(r"```json|```", "", text).strip()
            result = _json.loads(text)
            self.found.emit(result, self.lead_id)
        except Exception as e:
            self.error.emit(str(e))


class GrabPhoneWorker(QThread):
    found = pyqtSignal(str, int)
    error = pyqtSignal(str)

    def __init__(self, url, lead_id):
        super().__init__()
        self.url     = url
        self.lead_id = lead_id

    def run(self):
        try:
            import re, time as _time
            from selenium import webdriver
            from selenium.webdriver.firefox.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            ad_id_match = re.search(r"/(\d{7,12})(?:[/?]|$)", self.url)
            if not ad_id_match:
                self.error.emit("Could not extract ad ID from URL")
                return
            ad_id = ad_id_match.group(1)

            # Load Firefox cookies
            try:
                import browser_cookie3
                ff_cookies = browser_cookie3.firefox(domain_name=".kijiji.ca")
                cookie_dict = {c.name: c.value for c in ff_cookies}
            except Exception:
                cookie_dict = {}

            options = Options()
            options.add_argument("--headless")
            driver = webdriver.Firefox(options=options)

            try:
                driver.get("https://www.kijiji.ca")
                for name, value in cookie_dict.items():
                    try:
                        driver.add_cookie({"name": name, "value": value, "domain": ".kijiji.ca"})
                    except Exception:
                        pass

                reveal_url = "https://www.kijiji.ca/v-get-phone-number/" + ad_id
                driver.get(reveal_url)
                _time.sleep(2)

                # Click any reveal/show phone button
                try:
                    btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH,
                            "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'reveal') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show phone')]"
                        ))
                    )
                    btn.click()
                    _time.sleep(2)
                except Exception:
                    pass

                page_text = driver.find_element(By.TAG_NAME, "body").text
                phones = re.findall(r"\+?1?[\s.\-]?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", page_text)

                if phones:
                    raw = re.sub(r"\D", "", phones[0])
                    if len(raw) >= 10:
                        d = raw[-10:]
                        phone = "(" + d[:3] + ") " + d[3:6] + "-" + d[6:]
                        self.found.emit(phone, self.lead_id)
                        return

                self.error.emit("Phone not found — owner may not have listed one")
            finally:
                driver.quit()

        except Exception as e:
            self.error.emit(str(e))


class SpeakWorker(QThread):
    """Generates TTS audio and plays it via ffplay at speed 1.2."""
    started_playing = pyqtSignal()
    finished_playing = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, text, speed=1.2):
        super().__init__()
        self.text  = text
        self.speed = speed
        self._stop = False

    def run(self):
        try:
            from gtts import gTTS
            import tempfile, os, subprocess
            tts = gTTS(text=self.text, lang='en', tld='ca')
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                tts.save(f.name)
                tmp = f.name
            self.started_playing.emit()
            subprocess.run(
                ['ffplay', '-nodisp', '-autoexit', '-af', f'atempo={self.speed}', tmp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            os.unlink(tmp)
            self.finished_playing.emit()
        except ImportError:
            self.error.emit("gTTS not installed. Run: pip install gtts --break-system-packages")
        except FileNotFoundError:
            self.error.emit("ffplay not found. Run: sudo apt install ffmpeg")
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        import subprocess
        self._stop = True
        subprocess.run(['pkill', '-f', 'ffplay'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)



# ─── Scraper Worker ──────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

class ScrapeWorker(QThread):
    result    = pyqtSignal(list)   # list of dicts
    progress  = pyqtSignal(str)
    error     = pyqtSignal(str)

    def __init__(self, mode, area, pages=3):
        super().__init__()
        self.mode  = mode   # 'agents' | 'property_mgrs' | 'landlords'
        self.area  = area
        self.pages = pages

    def run(self):
        try:
            # Load Firefox cookies for authenticated requests
            try:
                import browser_cookie3
                cookies = browser_cookie3.firefox(domain_name=".kijiji.ca")
                self.cookies = {c.name: c.value for c in cookies}
                self.progress.emit(f"Using Firefox session ({len(self.cookies)} cookies loaded)")
            except Exception:
                self.cookies = {}
                self.progress.emit("No Firefox cookies — using anonymous session")

            if self.mode == "agents":
                results = self.scrape_agents()
            elif self.mode == "property_mgrs":
                results = self.scrape_property_mgrs()
            elif self.mode == "landlords":
                results = self.scrape_landlords()
            elif self.mode == "condos":
                results = self.scrape_condos()
            else:
                results = []
            self.result.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    # ── Real estate agents from realtor.ca listing pages ──
    def scrape_agents(self):
        leads = []
        area_slug = self.area.lower().replace(" ", "-")
        self.progress.emit(f"Searching realtor.ca for agents in {self.area}…")

        # realtor.ca search — pull listing agent cards
        url = f"https://www.realtor.ca/map#ZoomLevel=12&LatitudeMax=43.8&LatitudeMin=43.5&LongitudeMax=-79.3&LongitudeMin=-79.7&Sort=6-D&PropertyTypeGroupID=1&TransactionTypeId=2&Currency=CAD"

        # Use the public find-an-agent endpoint
        search_url = "https://api2.realtor.ca/Listing.svc/PropertySearch_Post"
        payload = {
            "ZoomLevel": 12,
            "LatitudeMax": "43.8500",
            "LatitudeMin": "43.5800",
            "LongitudeMax": "-79.3000",
            "LongitudeMin": "-79.6500",
            "Sort": "6-D",
            "PropertyTypeGroupID": "1",
            "TransactionTypeId": "2",
            "RecordsPerPage": "50",
            "ApplicationId": "1",
            "CultureId": "1",
            "Version": "7.0",
            "CurrentPage": "1",
        }
        seen_agents = set()

        for page in range(1, self.pages + 1):
            payload["CurrentPage"] = str(page)
            self.progress.emit(f"Pulling realtor.ca page {page}/{self.pages}…")
            try:
                r = requests.post(search_url, data=payload, headers=HEADERS, timeout=15)
                data = r.json()
                listings = data.get("Results", [])
                for listing in listings:
                    for agent in listing.get("Individual", []):
                        # PhoneNumber can be a dict with AreaCode+Number, or a plain string
                        pn = agent.get("PhoneNumber") or {}
                        if isinstance(pn, dict):
                            raw = pn.get("AreaCode", "") + pn.get("Number", "")
                        else:
                            raw = str(pn)
                        # Also check Phones list if present
                        if not raw.strip():
                            for ph_entry in agent.get("Phones", []):
                                raw = str(ph_entry.get("PhoneNumber", ""))
                                if raw:
                                    break
                        digits = re.sub(r"\D", "", raw)
                        if len(digits) >= 10:
                            d = digits[-10:]
                            phone = f"({d[:3]}) {d[3:6]}-{d[6:]}"
                        else:
                            phone = ""

                        name = f"{agent.get('FirstName','')} {agent.get('LastName','')}".strip()
                        org  = agent.get("OrganizationName", "")
                        key  = name + phone

                        if key in seen_agents or not name:
                            continue
                        seen_agents.add(key)

                        leads.append({
                            "name":    name,
                            "company": org,
                            "phone":   phone,
                            "email":   agent.get("EmailAddress", ""),
                            "type":    "Agent",
                            "area":    self.area,
                            "source":  "realtor.ca scrape",
                        })
                time.sleep(1.2)
            except Exception as e:
                self.progress.emit(f"Page {page} error: {e}")

        self.progress.emit(f"Found {len(leads)} agents from realtor.ca")
        return leads

    # ── Property management companies — multi-source with phone extraction ──
    def scrape_property_mgrs(self):
        leads = []
        seen  = set()

        # Strategy: search DuckDuckGo HTML version (no JS required, shows phone in snippets)
        # then Yellow Pages, then fallback to Bing HTML
        search_queries = [
            f'property management company {self.area} Ontario phone',
            f'property manager {self.area} Toronto rental phone number',
            f'residential property management {self.area} GTA contact',
        ]

        # ── DuckDuckGo HTML (no JS, phone numbers appear in snippets) ──
        for q in search_queries[:self.pages]:
            self.progress.emit(f"Searching: {q[:50]}…")
            try:
                url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(q)}"
                r = requests.get(url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")

                for result in soup.select("div.result, div.web-result"):
                    title_el   = result.select_one("a.result__a, h2 a, .result__title a")
                    snippet_el = result.select_one("a.result__snippet, .result__snippet, .result__body")
                    if not title_el:
                        continue

                    name    = title_el.get_text(strip=True)
                    snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
                    combined = name + " " + snippet

                    # Only keep results that look like property management businesses
                    keywords = ["property", "management", "real estate", "rental", "realty"]
                    if not any(k in combined.lower() for k in keywords):
                        continue
                    if name in seen or len(name) < 4:
                        continue

                    # Extract phone from snippet — Canadian formats
                    phone = self._extract_phone(combined)

                    seen.add(name)
                    leads.append({
                        "name":    name,
                        "company": name,
                        "phone":   phone,
                        "email":   "",
                        "type":    "Property Mgr",
                        "area":    self.area,
                        "source":  "DDG search",
                    })

                time.sleep(2)
            except Exception as e:
                self.progress.emit(f"Search error: {e}")

        # ── Yellow Pages Canada (static HTML fallback) ──
        self.progress.emit("Checking Yellow Pages Canada…")
        for page in range(1, min(self.pages, 4) + 1):
            try:
                yp_url = (
                    f"https://www.yellowpages.ca/search/si/{page}/"
                    f"property+management/{self.area.replace(' ', '+')}+ON"
                )
                r = requests.get(yp_url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")

                # YP renders name + phone in <script type="application/ld+json"> blocks
                for script in soup.select("script[type='application/ld+json']"):
                    try:
                        import json as _json
                        data = _json.loads(script.string or "")
                        # Can be a list or single object
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            name = item.get("name", "")
                            phone = item.get("telephone", "")
                            if not name or name in seen:
                                continue
                            if phone:
                                digits = re.sub(r"\D", "", phone)
                                if len(digits) >= 10:
                                    d = digits[-10:]
                                    phone = f"({d[:3]}) {d[3:6]}-{d[6:]}"
                            seen.add(name)
                            leads.append({
                                "name":    name,
                                "company": name,
                                "phone":   phone,
                                "email":   item.get("email", ""),
                                "type":    "Property Mgr",
                                "area":    self.area,
                                "source":  "Yellow Pages",
                            })
                    except Exception:
                        pass

                # Also try visible HTML cards (for older YP page formats)
                for card in soup.select("div.listing__content, article[class*='listing']"):
                    name_el  = card.select_one("a[class*='name'], h3 a, h2 a")
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if not name or name in seen:
                        continue
                    # Phone from tel: link or text
                    phone = ""
                    tel_el = card.select_one("a[href^='tel:']")
                    if tel_el:
                        phone = self._extract_phone(tel_el.get("href","") + " " + tel_el.get_text())
                    if not phone:
                        phone = self._extract_phone(card.get_text(" ", strip=True))
                    seen.add(name)
                    leads.append({
                        "name": name, "company": name, "phone": phone,
                        "email": "", "type": "Property Mgr",
                        "area": self.area, "source": "Yellow Pages",
                    })

                time.sleep(1.5)
            except Exception as e:
                self.progress.emit(f"YP page {page} error: {e}")

        self.progress.emit(f"Found {len(leads)} property managers")
        return leads

    def _extract_phone(self, text):
        """Extract and format a Canadian phone number from any text blob."""
        # Match (416) 555-1234 / 416-555-1234 / 416.555.1234 / +14165551234
        patterns = [
            r"\+?1?\s*\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}",
            r"\b\d{3}[\-\.]\d{3}[\-\.]\d{4}\b",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                digits = re.sub(r"\D", "", m.group(0))
                if len(digits) >= 10:
                    d = digits[-10:]
                    return f"({d[:3]}) {d[3:6]}-{d[6:]}"
        return ""

    # ── Landlords from Kijiji rental listings ──
    def scrape_landlords(self):
        leads = []
        seen  = set()
        area_slug = self.area.lower().replace(" ", "-")
        self.progress.emit(f"Scanning Kijiji rentals in {self.area}…")

        try:
            url = f"https://www.kijiji.ca/b-apartments-condos/{area_slug}/k0c37l{self._kijiji_location_code()}?ad=offering"
            r = requests.get(url, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "html.parser")

            for ad in soup.select("li[data-listing-id]"):
                title_el   = ad.select_one("a.title")
                desc_el    = ad.select_one("div.description")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                desc  = desc_el.get_text(" ", strip=True) if desc_el else ""
                phone_match = re.search(r"\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}", desc)
                phone = phone_match.group(0) if phone_match else ""

                ad_id = ad.get("data-listing-id", "")
                if ad_id in seen:
                    continue
                seen.add(ad_id)

                leads.append({
                    "name":    f"Landlord – {title[:40]}",
                    "company": "",
                    "phone":   phone,
                    "email":   "",
                    "type":    "Landlord",
                    "area":    self.area,
                    "source":  "Kijiji",
                })
            time.sleep(1)
        except Exception as e:
            self.progress.emit(f"Kijiji error: {e}")

        self.progress.emit(f"Found {len(leads)} Kijiji landlord listings")
        return leads

    def scrape_condos(self):
        """Scrape private condo owners from Kijiji using __NEXT_DATA__ JSON."""
        leads = []
        seen  = set()

        location_codes = {
            "etobicoke":   "1700273",
            "toronto":     "1700273",
            "north york":  "1700273",
            "scarborough": "1700273",
            "mississauga": "1700199",
            "gta":         "1700273",
        }
        loc_code = location_codes.get(self.area.lower(), "1700273")

        for page in range(1, self.pages + 1):
            self.progress.emit(f"Scanning Kijiji private condo owners — page {page}/{self.pages}...")
            try:
                base_url = (
                    "https://www.kijiji.ca/b-apartments-condos/"
                    + self.area.lower().replace(" ", "-")
                    + "/k0c37l" + loc_code
                )
                url = base_url + (f"?page={page}" if page > 1 else "")
                r = requests.get(url, headers=HEADERS, timeout=15)

                import re as _re, json as _json
                pattern = r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>'
                match = _re.search(pattern, r.text)
                if not match:
                    self.progress.emit(f"Page {page}: no data found")
                    break

                data   = _json.loads(match.group(1))
                apollo = data["props"]["pageProps"]["__APOLLO_STATE__"]
                listing_keys = [k for k in apollo.keys() if "RealEstateListing:" in k]

                if not listing_keys:
                    self.progress.emit(f"Page {page}: no listings")
                    break

                for key in listing_keys:
                    ad    = apollo[key]
                    ad_id = str(ad.get("id", ""))
                    if ad_id in seen:
                        continue

                    # Private owners only
                    attrs = {}
                    for a in ad.get("attributes", {}).get("all", []):
                        attrs[a["canonicalName"]] = a["canonicalValues"]
                    owner_type = attrs.get("forrentbyhousing", [""])[0]
                    if owner_type not in ("ownr", ""):
                        continue

                    seen.add(ad_id)

                    title   = ad.get("title", "")[:50]
                    ad_url  = ad.get("url", "")
                    loc     = ad.get("location", {})
                    address = loc.get("address", self.area)

                    price_data = ad.get("price", {})
                    price_amt  = price_data.get("amount", 0)
                    price_str  = ("$" + str(int(price_amt/100)) + "/mo") if price_amt else ""

                    beds  = attrs.get("numberbedrooms", ["?"])[0]
                    desc  = ad.get("description", "")
                    phone = self._extract_phone(desc)

                    # Try to get phone via reveal endpoint using Firefox session
                    if not phone and ad_id:
                        try:
                            reveal_url = f"https://www.kijiji.ca/v-get-phone-number/{ad_id}"
                            r2 = requests.get(reveal_url, headers=HEADERS, cookies=self.cookies, timeout=10)
                            phones = re.findall(r"\+?1?[\s\.\-]?\(?\d{3}\)?[\s\.\-]\d{3}[\s\.\-]\d{4}", r2.text)
                            if phones:
                                raw = re.sub(r"\D", "", phones[0])
                                if len(raw) >= 10:
                                    d = raw[-10:]
                                    phone = f"({d[:3]}) {d[3:6]}-{d[6:]}"
                            time.sleep(0.5)
                        except Exception:
                            pass

                    note_parts = ["Kijiji: " + ad_url, "Address: " + address]
                    if price_str:
                        note_parts.append("Rent: " + price_str)
                    if beds:
                        note_parts.append("Bedrooms: " + str(beds))
                    notes = "\n".join(note_parts)

                    leads.append({
                        "name":    "Condo Owner - " + title,
                        "company": "",
                        "phone":   phone,
                        "email":   "",
                        "type":    "Condo Owner",
                        "area":    self.area,
                        "source":  "Kijiji",
                        "notes":   notes,
                    })

                self.progress.emit(
                    "Page " + str(page) + ": " + str(len(listing_keys)) +
                    " listings, " + str(len(leads)) + " private owners so far"
                )
                time.sleep(1.5)

            except Exception as e:
                self.progress.emit("Kijiji page " + str(page) + " error: " + str(e))

        # Keep only leads where we found a phone number
        leads_with_phone = [l for l in leads if l.get("phone")]
        no_phone = len(leads) - len(leads_with_phone)
        self.progress.emit(
            f"Found {len(leads_with_phone)} condo owners with phone numbers ({no_phone} skipped — no phone)"
        )
        return leads_with_phone



    def _kijiji_location_code(self):
        codes = {
            "etobicoke": "1700212",
            "toronto":   "1700273",
            "mississauga": "1700212",
            "north york": "1700193",
            "scarborough": "1700199",
            "gta":        "1700273",
        }
        return codes.get(self.area.lower(), "1700273")


# ─── Call Log Dialog ──────────────────────────────────────────────────────────

class CallLogDialog(QDialog):
    def __init__(self, lead_row, parent=None):
        super().__init__(parent)
        self.lead_id = lead_row["id"]
        self.setWindowTitle(f"Log Call — {lead_row['name']}")
        self.setMinimumWidth(420)
        self.setStyleSheet(parent.styleSheet() if parent else "")

        layout = QVBoxLayout(self)

        # Lead info summary
        info = QLabel(
            f"<b>{lead_row['name']}</b>"
            + (f" · {lead_row['company']}" if lead_row['company'] else "")
            + (f"<br>📞 {lead_row['phone']}" if lead_row['phone'] else "")
        )
        info.setStyleSheet("padding: 8px; background: #1e2535; border-radius: 6px;")
        layout.addWidget(info)

        form = QFormLayout()

        self.outcome_cb = QComboBox()
        self.outcome_cb.addItems([
            "Answered — Interested",
            "Answered — Not Interested",
            "Answered — Call Back",
            "Answered — Call back in 8 days",
            "Answered — Call back in 14 days",
            "Answered — Call back in 30 days",
            "Voicemail Left",
            "No Answer",
            "Job Booked 🎉",
        ])
        self.outcome_cb.currentTextChanged.connect(self._auto_set_followup)
        form.addRow("Outcome:", self.outcome_cb)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("What did they say? Any details…")
        self.notes_edit.setFixedHeight(100)
        form.addRow("Notes:", self.notes_edit)

        # Show last call note as reference
        try:
            with get_conn() as conn:
                last = conn.execute(
                    "SELECT outcome, notes, called_at FROM call_log WHERE lead_id=? ORDER BY id DESC LIMIT 1",
                    (self.lead_id,)
                ).fetchone()
            if last and last["notes"]:
                ref = QLabel(f"Last call ({last['called_at'][:10]}): {last['outcome']}\n{last['notes'][:120]}")
                ref.setWordWrap(True)
                ref.setStyleSheet("color: #4b5563; font-size: 11px; padding: 4px; background: #0e1420; border-radius: 4px;")
                form.addRow("", ref)
        except Exception:
            pass

        self.move_list = QComboBox()
        self.move_list.addItems(["— keep current list —", "Leads", "Follow-Up", "Warm", "Won", "Dead"])
        form.addRow("Move to list:", self.move_list)

        self.followup_date = QDateEdit()
        self.followup_date.setCalendarPopup(True)
        self.followup_date.setSpecialValueText("No follow-up")
        self.followup_date.setDate(QDate.currentDate())
        self.followup_date.setMinimumDate(QDate.currentDate())
        self.followup_date.setStyleSheet(
            "QDateEdit { background: #1e2535; color: #e2e8f0; border: 1px solid #2d3748;"
            "border-radius: 5px; padding: 6px 10px; }"
            "QDateEdit::drop-down { width: 20px; }"
            "QCalendarWidget { background: #1e2535; color: #e2e8f0; }"
        )
        form.addRow("Follow-up date:", self.followup_date)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _auto_set_followup(self, outcome):
        """Auto-set follow-up date based on outcome selection."""
        from datetime import timedelta
        days = None
        if "8 days" in outcome:
            days = 8
        elif "14 days" in outcome:
            days = 14
        elif "30 days" in outcome:
            days = 30
        elif "Voicemail" in outcome:
            days = 3
        elif "Call Back" in outcome and "days" not in outcome:
            days = 2
        if days:
            target = QDate.currentDate().addDays(days)
            self.followup_date.setDate(target)

    def save(self):
        outcome    = self.outcome_cb.currentText()
        notes      = self.notes_edit.toPlainText().strip()
        move_to    = self.move_list.currentText()
        followup   = self.followup_date.date().toString("yyyy-MM-dd") if self.followup_date.date() != QDate.currentDate().addDays(-1) else ""

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO call_log (lead_id, outcome, notes) VALUES (?,?,?)",
                (self.lead_id, outcome, notes)
            )
            updates = {
                "last_contact": date.today().isoformat(),
                "call_count":   None,  # handled below
            }
            if move_to != "— keep current list —":
                updates["list"] = move_to
            if followup:
                updates["next_followup"] = followup

            # Append call notes to lead notes
            if notes:
                existing = conn.execute(
                    "SELECT notes FROM leads WHERE id=?", (self.lead_id,)
                ).fetchone()
                existing_notes = (existing[0] or "") if existing else ""
                stamp = f"[{date.today().isoformat()} — {outcome}]\n{notes}"
                new_notes = (existing_notes + "\n\n" + stamp).strip()
                updates["notes"] = new_notes

            set_clause = ", ".join(
                f"{k} = ?" for k in updates if k != "call_count"
            )
            vals = [updates[k] for k in updates if k != "call_count"]
            if set_clause:
                conn.execute(
                    f"UPDATE leads SET {set_clause}, call_count = call_count + 1 WHERE id = ?",
                    vals + [self.lead_id]
                )
            else:
                conn.execute(
                    "UPDATE leads SET call_count = call_count + 1 WHERE id = ?",
                    (self.lead_id,)
                )
        self.accept()


# ─── Add / Edit Lead Dialog ───────────────────────────────────────────────────

class LeadDialog(QDialog):
    def __init__(self, lead=None, parent=None):
        super().__init__(parent)
        self.lead = lead
        self.setWindowTitle("Add Lead" if not lead else f"Edit — {lead['name']}")
        self.setMinimumWidth(440)
        self.setStyleSheet(parent.styleSheet() if parent else "")

        layout = QVBoxLayout(self)
        form   = QFormLayout()

        self.name_edit    = QLineEdit(lead["name"]    if lead else "")
        self.company_edit = QLineEdit(lead["company"] if lead else "")
        self.phone_edit   = QLineEdit(lead["phone"]   if lead else "")
        self.email_edit   = QLineEdit(lead["email"]   if lead else "")
        self.area_edit    = QLineEdit(lead["area"]    if lead else "Etobicoke")

        self.type_cb = QComboBox()
        self.type_cb.addItems(["Agent", "Property Mgr", "Landlord", "Condo Owner", "Staging", "Other"])
        if lead:
            self.type_cb.setCurrentText(lead["type"])

        self.list_cb = QComboBox()
        self.list_cb.addItems(["Leads", "Follow-Up", "Warm", "Won", "Dead"])
        if lead:
            self.list_cb.setCurrentText(lead["list"])

        self.priority_cb = QComboBox()
        self.priority_cb.addItems(["High", "Normal", "Low"])
        if lead:
            self.priority_cb.setCurrentText(lead["priority"])

        self.notes_edit = QTextEdit(lead["notes"] if lead else "")
        self.notes_edit.setFixedHeight(80)

        self.followup_edit = QDateEdit()
        self.followup_edit.setCalendarPopup(True)
        self.followup_edit.setSpecialValueText("No follow-up")
        self.followup_edit.setStyleSheet(
            "QDateEdit { background: #1e2535; color: #e2e8f0; border: 1px solid #2d3748;"
            "border-radius: 5px; padding: 6px 10px; }"
            "QCalendarWidget { background: #1e2535; color: #e2e8f0; }"
        )
        if lead and lead["next_followup"]:
            self.followup_edit.setDate(QDate.fromString(lead["next_followup"], "yyyy-MM-dd"))
        else:
            self.followup_edit.setDate(QDate.currentDate())
        self.followup_edit.setCalendarPopup(True)

        form.addRow("Name *",        self.name_edit)
        form.addRow("Company",       self.company_edit)
        form.addRow("Phone",         self.phone_edit)
        form.addRow("Email",         self.email_edit)
        form.addRow("Area",          self.area_edit)
        form.addRow("Type",          self.type_cb)
        form.addRow("List",          self.list_cb)
        form.addRow("Priority",      self.priority_cb)
        form.addRow("Follow-up",     self.followup_edit)
        form.addRow("Notes",         self.notes_edit)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Name is required.")
            return

        data = {
            "name":         name,
            "company":      self.company_edit.text().strip(),
            "phone":        self.phone_edit.text().strip(),
            "email":        self.email_edit.text().strip(),
            "area":         self.area_edit.text().strip(),
            "type":         self.type_cb.currentText(),
            "list":         self.list_cb.currentText(),
            "priority":     self.priority_cb.currentText(),
            "next_followup": self.followup_edit.date().toString("yyyy-MM-dd") if self.followup_edit.date().isValid() else None,
            "notes":        self.notes_edit.toPlainText().strip(),
        }

        with get_conn() as conn:
            if self.lead:
                conn.execute("""
                    UPDATE leads SET name=:name, company=:company, phone=:phone,
                    email=:email, area=:area, type=:type, list=:list,
                    priority=:priority, next_followup=:next_followup, notes=:notes
                    WHERE id=:id
                """, {**data, "id": self.lead["id"]})
            else:
                conn.execute("""
                    INSERT INTO leads (name,company,phone,email,area,type,list,priority,next_followup,notes)
                    VALUES (:name,:company,:phone,:email,:area,:type,:list,:priority,:next_followup,:notes)
                """, data)
        self.accept()


# ─── Scrape Dialog ────────────────────────────────────────────────────────────

class ScrapeDialog(QDialog):
    scraped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scrape New Leads")
        self.setMinimumWidth(480)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self._results = []

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.area_edit = QLineEdit("Etobicoke")
        self.mode_cb   = QComboBox()
        self.mode_cb.addItems([
            "Real Estate Agents (realtor.ca)",
            "Property Managers (Google / Yellow Pages)",
            "Landlords (Kijiji)",
            "Condo Owners (Kijiji + realtor.ca)",
        ])
        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(1, 10)
        self.pages_spin.setValue(3)
        self.pages_spin.setSuffix(" pages")
        form.addRow("Area / City:",  self.area_edit)
        form.addRow("Source:",       self.mode_cb)
        form.addRow("Depth:",        self.pages_spin)
        layout.addLayout(form)

        self.run_btn = QPushButton("▶  Start Scraping")
        self.run_btn.clicked.connect(self.start_scrape)
        layout.addWidget(self.run_btn)

        self.progress = QLabel("Ready.")
        self.progress.setStyleSheet("color: #7ecfff; font-size: 12px;")
        layout.addWidget(self.progress)

        self.pbar = QProgressBar()
        self.pbar.setRange(0, 0)
        self.pbar.hide()
        layout.addWidget(self.pbar)

        # Preview table
        self.preview = QTableWidget(0, 5)
        self.preview.setHorizontalHeaderLabels(["Name", "Company", "Phone", "Type", "Source"])
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setMinimumHeight(220)
        layout.addWidget(self.preview)

        self.count_label = QLabel("")
        layout.addWidget(self.count_label)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText("Add All to Leads")
        self.ok_btn.setEnabled(False)
        btns.accepted.connect(self.accept_results)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def start_scrape(self):
        mode_map = {0: "agents", 1: "property_mgrs", 2: "landlords", 3: "condos"}
        mode  = mode_map[self.mode_cb.currentIndex()]
        area  = self.area_edit.text().strip() or "Etobicoke"
        pages = self.pages_spin.value()

        self.run_btn.setEnabled(False)
        self.pbar.show()
        self._worker = ScrapeWorker(mode, area, pages)
        self._worker.progress.connect(self.progress.setText)
        self._worker.result.connect(self.on_results)
        self._worker.error.connect(lambda e: self.progress.setText(f"Error: {e}"))
        self._worker.finished.connect(lambda: (self.run_btn.setEnabled(True), self.pbar.hide()))
        self._worker.start()

    def on_results(self, results):
        self._results = results
        self.preview.setRowCount(0)
        for r in results:
            row = self.preview.rowCount()
            self.preview.insertRow(row)
            self.preview.setItem(row, 0, QTableWidgetItem(r.get("name", "")))
            self.preview.setItem(row, 1, QTableWidgetItem(r.get("company", "")))
            self.preview.setItem(row, 2, QTableWidgetItem(r.get("phone", "")))
            self.preview.setItem(row, 3, QTableWidgetItem(r.get("type", "")))
            self.preview.setItem(row, 4, QTableWidgetItem(r.get("source", "")))

        self.count_label.setText(f"✅ {len(results)} leads found — review above, then click 'Add All to Leads'")
        self.ok_btn.setEnabled(len(results) > 0)

    def accept_results(self):
        if not self._results:
            self.reject()
            return
        self.scraped.emit(self._results)
        self.accept()


# ─── Main Window ──────────────────────────────────────────────────────────────

STYLE = """
QMainWindow, QDialog { background: #121826; color: #e2e8f0; }
QWidget { background: #121826; color: #e2e8f0; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13px; }
QTabWidget::pane { border: 1px solid #2d3748; background: #121826; }
QTabBar::tab { background: #1e2535; color: #94a3b8; padding: 8px 18px; border: none; border-right: 1px solid #2d3748; }
QTabBar::tab:selected { background: #253048; color: #f0f4ff; border-bottom: 2px solid #f97316; }
QTabBar::tab:hover { background: #2a3650; }
QTableWidget { background: #161e2e; gridline-color: #243050; border: none; }
QTableWidget::item { padding: 6px 10px; border: none; }
QTableWidget::item:selected { background: #1e3a5f; color: #fff; }
QHeaderView::section { background: #1e2535; color: #94a3b8; padding: 6px 10px; border: none; border-bottom: 1px solid #2d3748; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
QPushButton { background: #f97316; color: #fff; border: none; border-radius: 6px; padding: 7px 18px; font-weight: 600; }
QPushButton:hover { background: #fb923c; }
QPushButton:disabled { background: #374151; color: #6b7280; }
QPushButton#secondary { background: #253048; color: #e2e8f0; }
QPushButton#secondary:hover { background: #2d3d5e; }
QPushButton#danger { background: #7f1d1d; color: #fecaca; }
QPushButton#danger:hover { background: #991b1b; }
QLineEdit, QComboBox, QTextEdit, QSpinBox {
    background: #1e2535; color: #e2e8f0; border: 1px solid #2d3748;
    border-radius: 5px; padding: 6px 10px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #f97316; }
QComboBox::drop-down { border: none; }
QComboBox::down-arrow { image: none; width: 12px; }
QComboBox QAbstractItemView { background: #1e2535; color: #e2e8f0; selection-background-color: #253048; border: 1px solid #2d3748; }
QLabel { color: #e2e8f0; }
QProgressBar { background: #1e2535; border: 1px solid #2d3748; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #f97316; border-radius: 4px; }
QStatusBar { background: #0e1420; color: #64748b; border-top: 1px solid #1e2535; font-size: 12px; }
QSplitter::handle { background: #2d3748; width: 1px; }
QScrollBar:vertical { background: #1e2535; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #374151; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialogButtonBox QPushButton { min-width: 80px; }
QFrame#card { background: #1a2235; border: 1px solid #253048; border-radius: 8px; }
"""

LIST_COLORS = {
    "Leads":      "#3b82f6",
    "Follow-Up":  "#f97316",
    "Warm":       "#22c55e",
    "Won":        "#a855f7",
    "Dead":       "#6b7280",
}
PRIORITY_COLORS = {
    "High":   "#ef4444",
    "Normal": "#94a3b8",
    "Low":    "#4b5563",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Old Pro CRM — Cold Call Tracker")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(STYLE)
        self._current_filter_list = "All"
        self._search_text = ""
        self._setup_ui()
        self._load_leads()
        self._start_followup_timer()
        self._update_scrape_label()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left sidebar
        sidebar = self._make_sidebar()
        root.addWidget(sidebar)

        # Main content
        content = QVBoxLayout()
        content.setContentsMargins(16, 12, 16, 12)
        content.setSpacing(10)

        # Toolbar row
        toolbar = self._make_toolbar()
        content.addLayout(toolbar)

        # Stats strip
        self.stats_bar = self._make_stats_bar()
        content.addLayout(self.stats_bar)

        # Splitter: table (top) + detail panel (bottom)
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = self._make_table()
        self.splitter.addWidget(self.table)

        self.detail = self._make_detail_panel()
        self.splitter.addWidget(self.detail)
        self.splitter.setSizes([520, 200])

        content.addWidget(self.splitter, 1)

        content_widget = QWidget()
        content_widget.setLayout(content)
        root.addWidget(content_widget, 1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _make_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("QFrame { background: #0e1420; border-right: 1px solid #1e2535; }")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        logo = QLabel("OLD PRO")
        logo.setStyleSheet("""
            color: #f97316; font-size: 15px; font-weight: 800;
            padding: 18px 16px 12px;
            letter-spacing: 2px;
            border-bottom: 1px solid #1e2535;
        """)
        layout.addWidget(logo)

        sub = QLabel("CRM")
        sub.setStyleSheet("color: #4b5563; font-size: 10px; padding: 0 16px 14px; letter-spacing: 3px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(sub)

        self.sidebar_btns = {}
        lists = ["All", "Leads", "Follow-Up", "Warm", "Won", "Dead"]
        icons = {"All": "◎", "Leads": "●", "Follow-Up": "▶", "Warm": "♦", "Won": "★", "Dead": "✕"}

        for lst in lists:
            btn = QPushButton(f"  {icons.get(lst,'')}  {lst}")
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: #94a3b8;
                    text-align: left; padding: 10px 16px;
                    border: none; border-radius: 0;
                    font-size: 13px;
                }}
                QPushButton:checked {{
                    background: #1e2535; color: #f0f4ff;
                    border-left: 3px solid {LIST_COLORS.get(lst, "#f97316")};
                }}
                QPushButton:hover {{ background: #1a2030; color: #e2e8f0; }}
            """)
            if lst == "All":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, l=lst: self._filter_by_list(l))
            self.sidebar_btns[lst] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Due today badge
        self.due_label = QLabel("")
        self.due_label.setStyleSheet("""
            color: #f97316; font-size: 11px; padding: 12px 16px;
            border-top: 1px solid #1e2535;
        """)
        self.due_label.setWordWrap(True)
        layout.addWidget(self.due_label)

        # Last scraped label
        self.scrape_label = QLabel("")
        self.scrape_label.setStyleSheet(
            "color: #4b5563; font-size: 10px; padding: 8px 16px 0px;"
        )
        self.scrape_label.setWordWrap(True)
        layout.addWidget(self.scrape_label)

        # API Key section
        key_frame = QFrame()
        key_frame.setStyleSheet("QFrame { border-top: 1px solid #1e2535; background: #0e1420; }")
        key_layout = QVBoxLayout(key_frame)
        key_layout.setContentsMargins(10, 10, 10, 10)
        key_layout.setSpacing(6)

        key_lbl = QLabel("OpenRouter Key")
        key_lbl.setStyleSheet("color: #4b5563; font-size: 10px; letter-spacing: 1px;")
        key_layout.addWidget(key_lbl)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("sk-or-…")
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setText(get_api_key())
        self.key_input.setStyleSheet(
            "font-size: 11px; padding: 5px 8px; border-radius: 4px;"
            "background: #1e2535; color: #e2e8f0; border: 1px solid #2d3748;"
        )
        key_layout.addWidget(self.key_input)

        save_key_btn = QPushButton("💾  Save Key")
        save_key_btn.setStyleSheet(
            "QPushButton { background: #1e3a5f; color: #7ecfff; font-size: 11px;"
            "padding: 5px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #1e4a7f; }"
        )
        save_key_btn.clicked.connect(self._save_api_key)
        key_layout.addWidget(save_key_btn)

        layout.addWidget(key_frame)

        return sidebar

    def _make_toolbar(self):
        row = QHBoxLayout()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search name, company, phone…")
        self.search_box.setFixedHeight(34)
        self.search_box.textChanged.connect(self._on_search)
        row.addWidget(self.search_box, 1)

        self.type_filter = QComboBox()
        self.type_filter.addItems(["All Types", "Agent", "Property Mgr", "Landlord", "Condo Owner", "Staging", "Other"])
        self.type_filter.currentTextChanged.connect(self._load_leads)
        row.addWidget(self.type_filter)

        scrape_btn = QPushButton("🌐  Scrape Leads")
        scrape_btn.setToolTip("Search realtor.ca, Yellow Pages and Kijiji for new leads")
        scrape_btn.clicked.connect(self._open_scrape)
        row.addWidget(scrape_btn)

        import_btn = QPushButton("📲  Import URL")
        import_btn.setObjectName("secondary")
        import_btn.setToolTip("Copy a Kijiji ad URL then click to import as a new lead")
        import_btn.clicked.connect(self._import_from_url)
        row.addWidget(import_btn)

        dedup_btn = QPushButton("🔍  Deduplicate")
        dedup_btn.setObjectName("secondary")
        dedup_btn.setToolTip("Find and merge duplicate leads, keeping the most complete record")
        dedup_btn.clicked.connect(self._deduplicate)
        row.addWidget(dedup_btn)

        add_btn = QPushButton("＋  Add Manual")
        add_btn.setObjectName("secondary")
        add_btn.clicked.connect(self._add_manual)
        row.addWidget(add_btn)

        quit_btn = QPushButton("⏻  Quit")
        quit_btn.setStyleSheet(
            "QPushButton { background: #3a0f0f; color: #f87171; font-size: 12px;"
            "padding: 7px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #7f1d1d; }"
        )
        quit_btn.clicked.connect(QApplication.quit)
        row.addWidget(quit_btn)

        return row

    def _make_stats_bar(self):
        row = QHBoxLayout()
        self.stat_labels = {}
        for key in ["Total", "Follow-Up Due", "Warm", "Won"]:
            frame = QFrame()
            frame.setObjectName("card")
            frame.setFixedHeight(52)
            fl = QHBoxLayout(frame)
            fl.setContentsMargins(14, 6, 14, 6)
            val = QLabel("0")
            val.setStyleSheet("font-size: 20px; font-weight: 700; color: #f0f4ff;")
            lbl = QLabel(key)
            lbl.setStyleSheet("font-size: 11px; color: #64748b;")
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(val)
            col.addWidget(lbl)
            fl.addLayout(col)
            row.addWidget(frame)
            self.stat_labels[key] = val
        return row

    def _make_table(self):
        t = QTableWidget()
        t.setColumnCount(9)
        t.setHorizontalHeaderLabels([
            "Priority", "Name", "Company", "Phone", "Type", "Area", "List", "Calls", "Follow-Up"
        ])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        t.setColumnWidth(0, 70)
        t.setColumnWidth(3, 120)
        t.setColumnWidth(4, 95)
        t.setColumnWidth(5, 90)
        t.setColumnWidth(6, 85)
        t.setColumnWidth(7, 55)
        t.setColumnWidth(8, 95)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(False)
        t.setSortingEnabled(True)
        t.itemSelectionChanged.connect(self._on_row_select)
        t.doubleClicked.connect(self._log_call)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._context_menu)
        return t

    def _make_detail_panel(self):
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet("QFrame#card { background: #161e2e; border: none; border-top: 1px solid #1e2535; }")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        # ── Left: lead info ──
        left = QVBoxLayout()
        left.setSpacing(4)
        self.detail_name = QLabel("Select a lead to view details")
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: 700; color: #f0f4ff;")
        self.detail_meta = QLabel("")
        self.detail_meta.setStyleSheet("color: #64748b; font-size: 12px;")
        self.detail_notes = QTextEdit()
        self.detail_notes.setReadOnly(True)
        self.detail_notes.setStyleSheet(
            "QTextEdit { color: #94a3b8; font-size: 12px; background: transparent;"
            "border: none; margin-top: 2px; }")
        left.addWidget(self.detail_name)
        left.addWidget(self.detail_meta)
        left.addWidget(self.detail_notes)

        self.detail_photo = QLabel("")
        self.detail_photo.setFixedHeight(120)
        self.detail_photo.setStyleSheet(
            "QLabel { background: #0e1420; border: 1px solid #1e2535; border-radius: 6px; }"
        )
        self.detail_photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_photo.hide()
        self.detail_photo.mouseDoubleClickEvent = self._open_photo_fullsize
        self.detail_photo.setCursor(Qt.CursorShape.PointingHandCursor)
        left.addWidget(self.detail_photo)

        left.addStretch()
        layout.addLayout(left, 1)

        # ── Centre: action buttons ──
        centre = QVBoxLayout()
        centre.setSpacing(6)
        centre.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.call_btn = QPushButton("📞  Log a Call")
        self.call_btn.setEnabled(False)
        self.call_btn.clicked.connect(self._log_call)
        centre.addWidget(self.call_btn)

        self.edit_btn = QPushButton("✏️  Edit Lead")
        self.edit_btn.setObjectName("secondary")
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._edit_lead)
        centre.addWidget(self.edit_btn)

        self.move_btn = QComboBox()
        self.move_btn.addItem("Move to list…")
        self.move_btn.addItems(["Leads", "Follow-Up", "Warm", "Won", "Dead"])
        self.move_btn.setEnabled(False)
        self.move_btn.currentTextChanged.connect(self._quick_move)
        centre.addWidget(self.move_btn)

        self.textnow_btn = QPushButton("📱  Call via TextNow")
        self.textnow_btn.setEnabled(False)
        self.textnow_btn.setStyleSheet(
            "QPushButton { background: #1a3a2a; color: #4ade80; font-size: 12px;"
            "padding: 7px 10px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #14532d; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.textnow_btn.clicked.connect(self._dial_textnow)
        centre.addWidget(self.textnow_btn)

        self.open_ad_btn = QPushButton("🌐  Open Ad")
        self.open_ad_btn.setEnabled(False)
        self.open_ad_btn.setStyleSheet(
            "QPushButton { background: #1a2a3a; color: #7ecfff; font-size: 12px;"
            "padding: 7px 10px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #1e3a5f; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.open_ad_btn.clicked.connect(self._open_ad)
        centre.addWidget(self.open_ad_btn)

        self.photo_btn = QPushButton("📷  Add Photo")
        self.photo_btn.setEnabled(False)
        self.photo_btn.setStyleSheet(
            "QPushButton { background: #1a2a3a; color: #7ecfff; font-size: 12px;"
            "padding: 7px 10px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #1e3a5f; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.photo_btn.clicked.connect(self._add_photo)
        centre.addWidget(self.photo_btn)

        self.card_btn = QPushButton("🪪  Read Card")
        self.card_btn.setEnabled(False)
        self.card_btn.setStyleSheet(
            "QPushButton { background: #2a1a3a; color: #c084fc; font-size: 12px;"
            "padding: 7px 10px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #3b1f5e; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.card_btn.clicked.connect(self._read_business_card)
        centre.addWidget(self.card_btn)

        self.del_btn = QPushButton("🗑  Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.setEnabled(False)
        self.del_btn.clicked.connect(self._delete_lead)
        centre.addWidget(self.del_btn)
        layout.addLayout(centre)

        # ── Right: AI assistant panel ──
        ai_frame = QFrame()
        ai_frame.setStyleSheet(
            "QFrame { background: #0e1420; border-radius: 8px; border: 1px solid #1e3a5f; }"
        )
        ai_frame.setFixedWidth(420)
        ai_layout = QVBoxLayout(ai_frame)
        ai_layout.setContentsMargins(10, 8, 10, 8)
        ai_layout.setSpacing(6)

        # Header row
        ai_header = QHBoxLayout()
        ai_title = QLabel("🤖  AI Assistant")
        ai_title.setStyleSheet("color: #7ecfff; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        ai_header.addWidget(ai_title)
        ai_header.addStretch()

        # Task selector
        self.ai_task_cb = QComboBox()
        self.ai_task_cb.addItems(["Call Opener", "Follow-Up SMS", "Qualify Lead", "Enrich / Extract"])
        self.ai_task_cb.setStyleSheet(
            "QComboBox { background: #1e2535; color: #e2e8f0; border: 1px solid #1e3a5f;"
            "border-radius: 4px; padding: 3px 8px; font-size: 11px; }"
            "QComboBox QAbstractItemView { background: #1e2535; color: #e2e8f0; }"
        )
        self.ai_task_cb.setFixedWidth(140)
        ai_header.addWidget(self.ai_task_cb)

        self.ai_run_btn = QPushButton("▶ Run")
        self.ai_run_btn.setEnabled(False)
        self.ai_run_btn.setFixedWidth(60)
        self.ai_run_btn.setStyleSheet(
            "QPushButton { background: #1e3a5f; color: #7ecfff; font-size: 11px;"
            "padding: 4px 8px; border-radius: 4px; font-weight: 700; }"
            "QPushButton:hover { background: #1e4a7f; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.ai_run_btn.clicked.connect(self._run_ai)
        ai_header.addWidget(self.ai_run_btn)
        ai_layout.addLayout(ai_header)

        # Extra context box (shown for Qualify/Enrich)
        self.ai_context = QLineEdit()
        self.ai_context.setPlaceholderText("Extra context or paste company info here…")
        self.ai_context.setStyleSheet(
            "QLineEdit { background: #1a2235; color: #94a3b8; border: 1px solid #1e3a5f;"
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; }"
        )
        ai_layout.addWidget(self.ai_context)

        # Output box — editable so Jo can tweak before copying
        self.ai_output = QTextEdit()
        self.ai_output.setPlaceholderText("AI output will appear here — editable before you copy or save…")
        self.ai_output.setStyleSheet(
            "QTextEdit { background: #0a1020; color: #c8e6ff; border: 1px solid #1e3a5f;"
            "border-radius: 4px; padding: 6px; font-size: 12px; line-height: 1.5; }"
        )
        self.ai_output.setMinimumHeight(80)
        ai_layout.addWidget(self.ai_output, 1)

        # Bottom row: save to notes + copy
        ai_bottom = QHBoxLayout()
        ai_bottom.setSpacing(6)

        self.ai_save_btn = QPushButton("💾  Save to Notes")
        self.ai_save_btn.setEnabled(False)
        self.ai_save_btn.setStyleSheet(
            "QPushButton { background: #14532d; color: #86efac; font-size: 11px;"
            "padding: 5px 10px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #166534; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.ai_save_btn.clicked.connect(self._save_ai_to_notes)
        ai_bottom.addWidget(self.ai_save_btn)

        self.ai_copy_btn = QPushButton("📋  Copy")
        self.ai_copy_btn.setEnabled(False)
        self.ai_copy_btn.setStyleSheet(
            "QPushButton { background: #1e2535; color: #94a3b8; font-size: 11px;"
            "padding: 5px 10px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #253048; color: #e2e8f0; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.ai_copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.ai_output.toPlainText())
        )
        ai_bottom.addWidget(self.ai_copy_btn)

        self.ai_speak_btn = QPushButton("🔊  Speak")
        self.ai_speak_btn.setEnabled(False)
        self.ai_speak_btn.setStyleSheet(
            "QPushButton { background: #1e3a2f; color: #4ade80; font-size: 11px;"
            "padding: 5px 10px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #14532d; color: #86efac; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.ai_speak_btn.clicked.connect(self._speak_ai)
        ai_bottom.addWidget(self.ai_speak_btn)

        self.ai_stop_btn = QPushButton("⏹  Stop")
        self.ai_stop_btn.setEnabled(False)
        self.ai_stop_btn.setStyleSheet(
            "QPushButton { background: #3b1f1f; color: #f87171; font-size: 11px;"
            "padding: 5px 10px; border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #7f1d1d; }"
            "QPushButton:disabled { background: #1a2235; color: #374151; }"
        )
        self.ai_stop_btn.clicked.connect(self._stop_speak)
        ai_bottom.addWidget(self.ai_stop_btn)

        ai_bottom.addStretch()

        self.ai_status = QLabel("")
        self.ai_status.setStyleSheet("color: #4b6b8a; font-size: 11px;")
        ai_bottom.addWidget(self.ai_status)

        ai_layout.addLayout(ai_bottom)
        layout.addWidget(ai_frame)

        return frame

    # ── Data Loading ──────────────────────────────────────────────────────────

    def _load_leads(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._lead_ids = []

        with get_conn() as conn:
            q = "SELECT * FROM leads WHERE 1=1"
            params = []
            if self._current_filter_list != "All":
                q += " AND list = ?"
                params.append(self._current_filter_list)
            if self._search_text:
                q += " AND (name LIKE ? OR company LIKE ? OR phone LIKE ? OR notes LIKE ?)"
                s = f"%{self._search_text}%"
                params += [s, s, s, s]
            type_f = self.type_filter.currentText() if hasattr(self, "type_filter") else "All Types"
            if type_f != "All Types":
                q += " AND type = ?"
                params.append(type_f)
            q += " ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Normal' THEN 1 ELSE 2 END, added DESC"
            rows = conn.execute(q, params).fetchall()

        today_str = date.today().isoformat()
        due_count = 0

        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._lead_ids.append(row["id"])

            # Priority dot
            p_item = QTableWidgetItem(row["priority"])
            p_item.setForeground(QColor(PRIORITY_COLORS.get(row["priority"], "#94a3b8")))
            self.table.setItem(r, 0, p_item)

            self.table.setItem(r, 1, QTableWidgetItem(row["name"] or ""))
            self.table.setItem(r, 2, QTableWidgetItem(row["company"] or ""))
            self.table.setItem(r, 3, QTableWidgetItem(row["phone"] or ""))
            self.table.setItem(r, 4, QTableWidgetItem(row["type"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(row["area"] or ""))

            list_item = QTableWidgetItem(row["list"] or "")
            list_item.setForeground(QColor(LIST_COLORS.get(row["list"], "#94a3b8")))
            self.table.setItem(r, 6, list_item)

            self.table.setItem(r, 7, QTableWidgetItem(str(row["call_count"] or 0)))

            fu = row["next_followup"] or ""
            fu_item = QTableWidgetItem(fu)
            if fu and fu <= today_str:
                fu_item.setForeground(QColor("#f97316"))
                due_count += 1
            self.table.setItem(r, 8, fu_item)
            # Green tint for called leads
            if (row["call_count"] or 0) > 0 and row["id"] != getattr(self, "_current_lead_id", None):
                for col in range(self.table.columnCount()):
                    item = self.table.item(r, col)
                    if item:
                        item.setBackground(QColor("#0e2a1a"))
                        item.setForeground(QColor("#86efac"))


        self.table.setSortingEnabled(True)
        self._update_stats(due_count)
        self.status.showMessage(f"{len(rows)} leads shown")

    def _update_stats(self, due_count=0):
        with get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            warm  = conn.execute("SELECT COUNT(*) FROM leads WHERE list='Warm'").fetchone()[0]
            won   = conn.execute("SELECT COUNT(*) FROM leads WHERE list='Won'").fetchone()[0]
            due   = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE next_followup <= ? AND next_followup IS NOT NULL AND next_followup != ''",
                (date.today().isoformat(),)
            ).fetchone()[0]

        self.stat_labels["Total"].setText(str(total))
        self.stat_labels["Follow-Up Due"].setText(str(due))
        self.stat_labels["Warm"].setText(str(warm))
        self.stat_labels["Won"].setText(str(won))

        if due > 0:
            self.due_label.setText(f"🔔 {due} follow-up{'s' if due>1 else ''}\ndue today")
        else:
            self.due_label.setText("✅ No follow-ups\ndue today")

    # ── Events ────────────────────────────────────────────────────────────────

    def _filter_by_list(self, lst):
        self._current_filter_list = lst
        for name, btn in self.sidebar_btns.items():
            btn.setChecked(name == lst)
        self._load_leads()

    def _on_search(self, text):
        self._search_text = text.strip()
        self._load_leads()

    def _selected_lead(self):
        rows = self.table.selectedItems()
        if not rows:
            return None
        row_idx = self.table.currentRow()
        if row_idx < 0 or row_idx >= len(self._lead_ids):
            return None
        lead_id = self._lead_ids[row_idx]
        with get_conn() as conn:
            return conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()

    def _on_row_select(self):
        lead = self._selected_lead()
        if not lead:
            return
        self.call_btn.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self.del_btn.setEnabled(True)
        self.move_btn.setEnabled(True)
        self.move_btn.blockSignals(True)
        self.move_btn.setCurrentIndex(0)
        self.move_btn.blockSignals(False)

        self.detail_name.setText(lead["name"])
        meta_parts = []
        if lead["company"]:  meta_parts.append(lead["company"])
        if lead["phone"]:    meta_parts.append(f"📞 {lead['phone']}")
        if lead["email"]:    meta_parts.append(f"✉️ {lead['email']}")
        if lead["last_contact"]: meta_parts.append(f"Last call: {lead['last_contact']}")
        if lead["next_followup"]: meta_parts.append(f"Follow-up: {lead['next_followup']}")
        meta_parts.append(f"{lead['call_count']} call{'s' if lead['call_count']!=1 else ''} logged")
        self.detail_meta.setText("  ·  ".join(meta_parts))
        self.detail_notes.setPlainText(lead["notes"] or "No notes yet.")
        self._show_lead_photo(lead)
        # Enable AI panel
        self.ai_run_btn.setEnabled(True)
        # Auto-grab phone if missing but URL in notes
        if not lead["phone"] and lead["notes"]:
            import re as _re2
            url_m = _re2.search(r"https?://[^\s]+kijiji[^\s]+", lead["notes"])
            if url_m:
                self.status.showMessage("🔄 Fetching phone via Selenium — please wait...")
                self._grab_phone_worker = GrabPhoneWorker(url_m.group(0).rstrip(".,)"), lead["id"])
                self._grab_phone_worker.found.connect(self._on_phone_grabbed)
                self._grab_phone_worker.error.connect(lambda e: (
                    self.status.showMessage("⚠️ No phone found — marked N/A"),
                    self._mark_no_phone(self._selected_lead()["id"] if self._selected_lead() else None)
                ))
                self._grab_phone_worker.start()
        self.textnow_btn.setEnabled(True)
        self.open_ad_btn.setEnabled(True)
        self.photo_btn.setEnabled(True)
        self.card_btn.setEnabled(True)

    def _log_call(self):
        lead = self._selected_lead()
        if not lead:
            return
        dlg = CallLogDialog(lead, self)
        if dlg.exec():
            self._load_leads()
            self.status.showMessage(f"Call logged for {lead['name']}")

    def _edit_lead(self):
        lead = self._selected_lead()
        if not lead:
            return
        dlg = LeadDialog(lead, self)
        if dlg.exec():
            self._load_leads()

    def _import_from_url(self):
        url = QApplication.clipboard().text().strip()
        if not url.startswith("http") or "kijiji" not in url:
            QMessageBox.information(self, "Import from URL",
                "Copy a Kijiji ad URL first (Ctrl+C in browser),\nthen click Import URL.")
            return
        self.status.showMessage("Fetching: " + url[:70])
        self._import_worker = ImportURLWorker(url)
        self._import_worker.found.connect(self._on_import_found)
        self._import_worker.error.connect(lambda e: self.status.showMessage("Import error: " + e))
        self._import_worker.start()

    def _on_import_found(self, data):
        import re
        phone = data.get("phone", "")
        notes = data.get("notes", "")

        # Extract address from notes for dupe check
        addr = ""
        addr_match = re.search(r"Address: (.+)", notes)
        if addr_match:
            addr = addr_match.group(1).strip()[:50]

        with get_conn() as conn:
            existing = None

            # Check by phone first
            if phone:
                existing = conn.execute(
                    "SELECT * FROM leads WHERE phone=?", (phone,)
                ).fetchone()

            # Check by address if no phone match
            if not existing and addr:
                existing = conn.execute(
                    "SELECT * FROM leads WHERE notes LIKE ?", (f"%{addr[:30]}%",)
                ).fetchone()

            if existing:
                # MERGE — fill in anything missing
                updates = {}
                if phone and not existing["phone"]:
                    updates["phone"] = phone
                if notes and not existing["notes"]:
                    updates["notes"] = notes
                elif notes and existing["notes"] and notes not in existing["notes"]:
                    # Append new notes without duplicating
                    updates["notes"] = existing["notes"] + "\n" + notes
                if data.get("email") and not existing["email"]:
                    updates["email"] = data["email"]

                if updates:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    conn.execute(
                        f"UPDATE leads SET {set_clause} WHERE id=?",
                        list(updates.values()) + [existing["id"]]
                    )
                    self._load_leads()
                    self.status.showMessage(
                        f"✅ Merged into: {existing['name']} — added: {', '.join(updates.keys())}"
                    )
                else:
                    self.status.showMessage(
                        f"Already complete: {existing['name']} — nothing new to add"
                    )
                return

            # No duplicate — create new lead
            conn.execute("""
                INSERT INTO leads (name,company,phone,email,type,area,source,notes,list)
                VALUES (:name,:company,:phone,:email,:type,:area,:source,:notes,'Leads')
            """, data)

        self._load_leads()
        self.status.showMessage(
            f"✅ Imported: {data['name']}" +
            (f" — {phone}" if phone else " — no phone found")
        )

    def _deduplicate(self):
        """Find duplicate leads, merge data into the most complete one, drop the rest."""
        import re
        from difflib import SequenceMatcher

        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()

        leads = [dict(r) for r in rows]
        merged_count  = 0
        dropped_count = 0
        processed_ids = set()

        def score(lead):
            """Score a lead by how much data it has."""
            return sum([
                bool(lead.get("phone")),
                bool(lead.get("email")),
                bool(lead.get("notes")),
                bool(lead.get("company")),
                bool(lead.get("last_contact")),
                (lead.get("call_count") or 0),
            ])

        def merge_into(winner, loser):
            """Merge loser data into winner, keeping best of each field."""
            updates = {}
            # Phone — keep winner's if exists, otherwise take loser's
            if not winner.get("phone") and loser.get("phone"):
                updates["phone"] = loser["phone"]
            # Email
            if not winner.get("email") and loser.get("email"):
                updates["email"] = loser["email"]
            # Notes — append unique content
            w_notes = winner.get("notes") or ""
            l_notes = loser.get("notes") or ""
            if l_notes and l_notes not in w_notes:
                updates["notes"] = (w_notes + "\n" + l_notes).strip()
            # Call count — add together
            if (loser.get("call_count") or 0) > 0:
                updates["call_count"] = (winner.get("call_count") or 0) + (loser.get("call_count") or 0)
            # Last contact — keep most recent
            w_lc = winner.get("last_contact") or ""
            l_lc = loser.get("last_contact") or ""
            if l_lc and l_lc > w_lc:
                updates["last_contact"] = l_lc
            # Priority — keep highest
            priority_rank = {"High": 0, "Normal": 1, "Low": 2}
            if priority_rank.get(loser.get("priority"), 1) < priority_rank.get(winner.get("priority"), 1):
                updates["priority"] = loser["priority"]
            # List — keep most advanced
            list_rank = {"Won": 0, "Warm": 1, "Follow-Up": 2, "Leads": 3, "Dead": 4}
            if list_rank.get(loser.get("list"), 3) < list_rank.get(winner.get("list"), 3):
                updates["list"] = loser["list"]
            return updates

        def is_duplicate(a, b):
            """Check if two leads are duplicates."""
            # Same phone
            if a.get("phone") and b.get("phone") and a["phone"] == b["phone"]:
                return True
            # Same address in notes
            def extract_addr(notes):
                m = re.search(r"Address: (.{10,50})", notes or "")
                return m.group(1).strip().lower() if m else ""
            addr_a = extract_addr(a.get("notes",""))
            addr_b = extract_addr(b.get("notes",""))
            if addr_a and addr_b and addr_a[:25] == addr_b[:25]:
                return True
            # Very similar name (same type)
            if a.get("type") == b.get("type"):
                name_a = re.sub(r"Condo Owner\s*[-–]?\s*", "", a.get("name","")).lower().strip()
                name_b = re.sub(r"Condo Owner\s*[-–]?\s*", "", b.get("name","")).lower().strip()
                if name_a and name_b and len(name_a) > 10:
                    ratio = SequenceMatcher(None, name_a, name_b).ratio()
                    if ratio > 0.85:
                        return True
            return False

        with get_conn() as conn:
            for i, lead_a in enumerate(leads):
                if lead_a["id"] in processed_ids:
                    continue
                group = [lead_a]
                for lead_b in leads[i+1:]:
                    if lead_b["id"] in processed_ids:
                        continue
                    if is_duplicate(lead_a, lead_b):
                        group.append(lead_b)

                if len(group) > 1:
                    # Pick winner — highest score
                    winner = max(group, key=score)
                    losers = [l for l in group if l["id"] != winner["id"]]

                    # Merge all losers into winner
                    all_updates = {}
                    for loser in losers:
                        updates = merge_into(winner, loser)
                        all_updates.update(updates)
                        # Update winner dict too for next merge
                        winner.update(updates)

                    if all_updates:
                        set_clause = ", ".join(f"{k}=?" for k in all_updates)
                        conn.execute(
                            f"UPDATE leads SET {set_clause} WHERE id=?",
                            list(all_updates.values()) + [winner["id"]]
                        )
                        merged_count += 1

                    # Delete losers
                    for loser in losers:
                        conn.execute("DELETE FROM leads WHERE id=?", (loser["id"],))
                        processed_ids.add(loser["id"])
                        dropped_count += 1

                processed_ids.add(lead_a["id"])

        self._load_leads()
        if merged_count == 0 and dropped_count == 0:
            self.status.showMessage("No duplicates found — list is clean")
        else:
            self.status.showMessage(
                f"✅ Deduplicated: {merged_count} merged, {dropped_count} duplicates removed"
            )

    def _mark_no_phone(self, lead_id):
        if not lead_id:
            return
        with get_conn() as conn:
            conn.execute("UPDATE leads SET phone=? WHERE id=?", ("N/A", lead_id))
        self._load_leads()

    def _on_phone_grabbed(self, phone, lead_id):
        with get_conn() as conn:
            conn.execute("UPDATE leads SET phone=? WHERE id=?", (phone, lead_id))
        self._load_leads()
        self.status.showMessage("✅ Phone saved: " + phone)
        # Play a soft chime sound
        import subprocess
        subprocess.Popen(
            ["python3", "-c",
             "from gtts import gTTS; import tempfile,os,subprocess; "
             "tts=gTTS('Got it',lang='en'); f=tempfile.NamedTemporaryFile(suffix='.mp3',delete=False); "
             "tts.save(f.name); subprocess.run(['ffplay','-nodisp','-autoexit','-af','atempo=1.3',f.name],"
             "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); os.unlink(f.name)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def _grab_from_clipboard(self):
        lead = self._selected_lead()
        if not lead:
            return
        url = QApplication.clipboard().text().strip()
        if not url.startswith("http") or "kijiji" not in url:
            self.status.showMessage("Copy a Kijiji ad URL first, then click Grab Phone")
            return
        self.status.showMessage("Fetching phone from: " + url[:60])
        notes = lead["notes"] or ""
        if url not in notes:
            new_notes = (notes + "\nKijiji: " + url).strip()
            with get_conn() as conn:
                conn.execute("UPDATE leads SET notes=? WHERE id=?", (new_notes, lead["id"]))
        self._grab_phone_worker = GrabPhoneWorker(url, lead["id"])
        self._grab_phone_worker.found.connect(self._on_phone_grabbed)
        self._grab_phone_worker.error.connect(lambda e: self.status.showMessage("Could not grab phone: " + e))
        self._grab_phone_worker.start()


    def _open_photo_fullsize(self, event=None):
        lead = self._selected_lead()
        if not lead:
            return
        import re as _re, subprocess
        notes = lead["notes"] or ""
        match = _re.search(r"\[PHOTO:([^\]]+)\]", notes)
        if match and Path(match.group(1)).exists():
            subprocess.Popen(["xdg-open", match.group(1)])

    def _show_lead_photo(self, lead):
        import re as _re
        notes = lead["notes"] or ""
        photo_match = _re.search(r"\[PHOTO:([^\]]+)\]", notes)
        if photo_match:
            photo_path = photo_match.group(1)
            if Path(photo_path).exists():
                from PyQt6.QtGui import QPixmap
                pixmap = QPixmap(photo_path).scaled(
                    300, 120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.detail_photo.setPixmap(pixmap)
                self.detail_photo.show()
                return
        self.detail_photo.hide()

    def _open_ad(self):
        lead = self._selected_lead()
        if not lead:
            return
        notes = lead["notes"] or ""
        import re as _re2, subprocess
        match = _re2.search(r"https?://[^\s]+kijiji[^\s]+", notes)
        if match:
            url = match.group(0).rstrip(".,)")
        else:
            name = lead["name"].replace("Condo Owner - ", "").strip()
            url = "https://www.kijiji.ca/b-apartments-condos/city-of-toronto/k0c37l1700273?q=" + requests.utils.quote(name)
        subprocess.Popen(["xdg-open", url])
        self.status.showMessage("Opened: " + url[:70])
        if not lead["phone"]:
            self.status.showMessage("Fetching phone via Selenium...")
            self._grab_phone_worker = GrabPhoneWorker(url, lead["id"])
            self._grab_phone_worker.found.connect(self._on_phone_grabbed)
            self._grab_phone_worker.error.connect(lambda e: self.status.showMessage("No phone found"))
            self._grab_phone_worker.start()

    def _add_photo(self):
        lead = self._selected_lead()
        if not lead:
            return
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Photo", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not file_path:
            return
        import shutil
        dest = IMAGES_PATH / ("lead_" + str(lead["id"]) + "_" + Path(file_path).name)
        shutil.copy2(file_path, dest)
        notes = lead["notes"] or ""
        import re as _re3
        notes = _re3.sub(r"\[PHOTO:[^\]]+\]\n?", "", notes).strip()
        new_notes = (notes + "\n[PHOTO:" + str(dest) + "]").strip()
        with get_conn() as conn:
            conn.execute("UPDATE leads SET notes=? WHERE id=?", (new_notes, lead["id"]))
        self._load_leads()
        self.status.showMessage("Photo saved for " + lead["name"])
        lead2 = self._selected_lead()
        if lead2:
            self._show_lead_photo(lead2)

    def _read_business_card(self):
        lead = self._selected_lead()
        if not lead:
            return
        key = get_api_key()
        if not key:
            self.status.showMessage("No OpenRouter API key saved")
            return
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Business Card Photo", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not file_path:
            return
        self.status.showMessage("Reading business card with AI...")
        self._card_worker = CardReaderWorker(file_path, lead["id"], key)
        self._card_worker.found.connect(self._on_card_read)
        self._card_worker.error.connect(lambda e: self.status.showMessage("Card error: " + e))
        self._card_worker.start()

    def _on_card_read(self, data, lead_id):
        with get_conn() as conn:
            lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            updates = {}
            if data.get("name") and (not lead["name"] or "Condo Owner" in (lead["name"] or "")):
                updates["name"] = data["name"]
            if data.get("phone") and not lead["phone"]:
                updates["phone"] = data["phone"]
            if data.get("email") and not lead["email"]:
                updates["email"] = data["email"]
            if data.get("company") and not lead["company"]:
                updates["company"] = data["company"]
            card_note = "\n".join(k + ": " + str(v) for k, v in data.items() if v)
            existing = lead["notes"] or ""
            updates["notes"] = (existing + "\n[Business Card]\n" + card_note).strip()
            if updates:
                set_clause = ", ".join(k + "=?" for k in updates)
                conn.execute(
                    "UPDATE leads SET " + set_clause + " WHERE id=?",
                    list(updates.values()) + [lead_id]
                )
        self._load_leads()
        filled = ", ".join(k for k in updates if k != "notes")
        self.status.showMessage("Card read — filled: " + filled)

    def _add_manual(self):
        dlg = LeadDialog(parent=self)
        if dlg.exec():
            self._load_leads()

    def _delete_lead(self):
        lead = self._selected_lead()
        if not lead:
            return
        resp = QMessageBox.question(
            self, "Delete Lead",
            f"Delete {lead['name']}? This also removes all call history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if resp == QMessageBox.StandardButton.Yes:
            with get_conn() as conn:
                conn.execute("DELETE FROM leads WHERE id=?", (lead["id"],))
            self._load_leads()

    def _quick_move(self, lst):
        if lst == "Move to list…":
            return
        lead = self._selected_lead()
        if not lead:
            return
        with get_conn() as conn:
            conn.execute("UPDATE leads SET list=? WHERE id=?", (lst, lead["id"]))
        self._load_leads()
        self.status.showMessage(f"Moved {lead['name']} → {lst}")

    def _context_menu(self, pos):
        lead = self._selected_lead()
        if not lead:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #1e2535; color: #e2e8f0; border: 1px solid #2d3748; }")
        menu.addAction("📞  Log Call",    self._log_call)
        menu.addAction("✏️  Edit",        self._edit_lead)
        menu.addSeparator()
        move_menu = menu.addMenu("Move to…")
        for lst in ["Leads", "Follow-Up", "Warm", "Won", "Dead"]:
            move_menu.addAction(lst, lambda l=lst: self._quick_move_direct(l))
        menu.addSeparator()
        if lead["phone"]:
            menu.addAction("📋  Copy Phone", lambda: QApplication.clipboard().setText(lead["phone"]))
        menu.addAction("🗑  Delete",       self._delete_lead)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _quick_move_direct(self, lst):
        lead = self._selected_lead()
        if not lead:
            return
        with get_conn() as conn:
            conn.execute("UPDATE leads SET list=? WHERE id=?", (lst, lead["id"]))
        self._load_leads()

    def _open_scrape(self):
        dlg = ScrapeDialog(self)
        dlg.scraped.connect(self._import_scraped)
        dlg.exec()

    def _import_scraped(self, results):
        added = 0
        with get_conn() as conn:
            existing_phones = {r[0] for r in conn.execute("SELECT phone FROM leads WHERE phone != ''").fetchall()}
            for r in results:
                if r.get("phone") and r["phone"] in existing_phones:
                    continue
                conn.execute("""
                    INSERT INTO leads (name,company,phone,email,type,area,source,list,notes)
                    VALUES (:name,:company,:phone,:email,:type,:area,:source,'Leads',:notes)
                """, {**r, "notes": r.get("notes", "")})
                added += 1
        # Save last scraped timestamp
        save_settings({"last_scraped": date.today().isoformat()})
        self._load_leads()
        self._update_scrape_label()
        self.status.showMessage(f"✅ Imported {added} new leads ({len(results)-added} duplicates skipped)")

    # ── API Key ───────────────────────────────────────────────────────────────

    def _save_api_key(self):
        key = self.key_input.text().strip()
        if not key:
            self.status.showMessage("Key is empty — nothing saved.")
            return
        save_settings({"openrouter_key": key})
        self.status.showMessage("✅ OpenRouter API key saved.")

    # ── AI Panel ──────────────────────────────────────────────────────────────

    def _on_row_select_ai(self):
        """Enable AI buttons when a lead is selected."""
        has_lead = self._selected_lead() is not None
        self.ai_run_btn.setEnabled(has_lead)

    def _run_ai(self):
        lead = self._selected_lead()
        if not lead:
            return

        task_map = {
            "Call Opener":       "opener",
            "Follow-Up SMS":     "followup",
            "Qualify Lead":      "qualify",
            "Enrich / Extract":  "enrich",
        }
        task  = task_map.get(self.ai_task_cb.currentText(), "opener")
        extra = self.ai_context.text().strip()

        self.ai_run_btn.setEnabled(False)
        self.ai_status.setText("Thinking…")
        self.ai_output.setPlainText("")
        self.ai_save_btn.setEnabled(False)
        self.ai_copy_btn.setEnabled(False)

        self._ai_worker = AIWorker(task, lead, extra)
        self._ai_worker.result.connect(self._on_ai_result)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.finished.connect(lambda: self.ai_run_btn.setEnabled(True))
        self._ai_worker.start()

    def _on_ai_result(self, text):
        self.ai_output.setPlainText(text)
        self.ai_status.setText("Done")
        self.ai_save_btn.setEnabled(True)
        self.ai_copy_btn.setEnabled(True)
        self.ai_speak_btn.setEnabled(True)

    def _on_ai_error(self, err):
        self.ai_output.setPlainText(f"Error: {err}")
        self.ai_status.setText("Error")

    def _dial_textnow(self):
        lead = self._selected_lead()
        if not lead:
            return
        phone = lead["phone"] if lead else ""
        if not phone:
            self.status.showMessage("No phone number for this lead.")
            return
        cb = QApplication.clipboard()
        cb.setText(phone)
        cb.setText(phone, cb.Mode.Selection)
        import subprocess
        subprocess.Popen(["xdg-open", "https://www.textnow.com/messaging"])
        self.status.showMessage(f"📋 {phone} copied — paste into TextNow dial pad")
        with get_conn() as conn:
            conn.execute(
                "UPDATE leads SET last_contact=?, call_count=call_count+1 WHERE id=?",
                (date.today().isoformat(), lead["id"])
            )
        self._load_leads()

    def _speak_ai(self):
        text = self.ai_output.toPlainText().strip()
        if not text:
            return
        self.ai_speak_btn.setEnabled(False)
        self.ai_stop_btn.setEnabled(True)
        self.ai_status.setText("Speaking…")
        self._speak_worker = SpeakWorker(text, speed=1.2)
        self._speak_worker.finished_playing.connect(self._on_speak_done)
        self._speak_worker.error.connect(lambda e: (
            self.ai_status.setText(f"Error: {e}"),
            self.ai_speak_btn.setEnabled(True),
            self.ai_stop_btn.setEnabled(False)
        ))
        self._speak_worker.start()

    def _stop_speak(self):
        if hasattr(self, '_speak_worker'):
            self._speak_worker.stop()
        self._on_speak_done()

    def _on_speak_done(self):
        self.ai_speak_btn.setEnabled(True)
        self.ai_stop_btn.setEnabled(False)
        self.ai_status.setText("Done")

    def _save_ai_to_notes(self):
        lead = self._selected_lead()
        if not lead:
            return
        text = self.ai_output.toPlainText().strip()
        if not text:
            return
        task  = self.ai_task_cb.currentText()
        stamp = f"[{date.today().isoformat()} — {task}]\n{text}"
        existing = lead["notes"] or ""
        new_notes = (existing + "\n\n" + stamp).strip()
        with get_conn() as conn:
            conn.execute("UPDATE leads SET notes=? WHERE id=?", (new_notes, lead["id"]))
        self._load_leads()
        self.ai_status.setText("Saved to notes ✓")

    # ── Follow-up reminder timer ───────────────────────────────────────────────

    def _update_scrape_label(self):
        last = load_settings().get("last_scraped", "")
        if not last:
            self.scrape_label.setText("Never scraped")
            self.scrape_label.setStyleSheet("color: #f97316; font-size: 10px; padding: 8px 16px 0px;")
            return
        from datetime import datetime
        last_date = datetime.strptime(last, "%Y-%m-%d").date()
        days_ago  = (date.today() - last_date).days
        if days_ago == 0:
            text  = "Scraped today"
            color = "#22c55e"
        elif days_ago <= 7:
            text  = f"Scraped {days_ago}d ago"
            color = "#22c55e"
        elif days_ago <= 14:
            text  = f"⚠️ Scraped {days_ago}d ago\nTime to re-scrape!"
            color = "#f97316"
        else:
            text  = f"🔴 Last scraped {days_ago}d ago\nScrape now!"
            color = "#ef4444"
        self.scrape_label.setText(text)
        self.scrape_label.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 8px 16px 0px; font-weight: 600;"
        )

    def _start_followup_timer(self):
        self._update_stats()
        timer = QTimer(self)
        timer.setInterval(60_000)  # check every minute
        timer.timeout.connect(self._update_stats)
        timer.start()


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("Old Pro CRM")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
