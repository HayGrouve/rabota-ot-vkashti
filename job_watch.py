"""Daily remote-job watch for a retired police officer living in Bulgaria.

Sources (all public and allowed):
  - zaplata.bg: ads sitemap (allowed by robots.txt); opens only ads whose category/title fits his roles.
  - Himalayas, Jobicy, Remote OK, Working Nomads, We Work Remotely, Remotive: public job APIs/feeds.
    Their terms ask for credit and a link to the original ad, which the report and page give.

Keeps only remote jobs open to someone living in Bulgaria, in roles that fit him, and drops jobs that
need special skills or a language other than Bulgarian and English. Each run writes:
  - reports/<date>.json and .md: jobs not seen before (the daily report),
  - jobs.json: every matching job still listed on its site (what the page shows first),
  - seen.json: jobs already checked, so they aren't reported twice,
and rebuilds the page into the site folder.

Usage: python3 -I job_watch.py [--all]   (--all re-reports everything, ignoring seen jobs)
Env:   JOBWATCH_DATA (state and reports, default: this folder), JOBWATCH_SITE (page, default: ./site)
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script dir from sys.path
import build_page  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("JOBWATCH_DATA") or HERE).resolve()
SITE = Path(os.environ.get("JOBWATCH_SITE") or HERE / "site").resolve()
STATE = DATA / "seen.json"
ACTIVE = DATA / "jobs.json"
REPORTS = DATA / "reports"
TZ = ZoneInfo("Europe/Sofia")
SEEN_DAYS = 30  # forget jobs gone from their site this long ago
UA = "Mozilla/5.0 (X11; Linux x86_64) JobWatch/1.0 (personal daily job alert)"
DELAY = 1.5  # seconds between requests to the same site
MAX_FETCH = 400

# --- zaplata.bg -------------------------------------------------------------------------------
ZAPLATA_SITEMAP = "https://www.zaplata.bg/sitemap.xml"
# URL categories worth opening for any title.
TARGET_CATS = {
    "logistika-speditsiia", "kontakt-tsentrove-call-centers", "ohrana", "administrativni-deynosti",
    "darzhavna-administratsiia", "drugo", "pravo-yuridicheski-uslugi", "bankovo-delo-i-finansi",
}
# Title slugs (transliterated) that fit his roles regardless of category.
SLUG_RE = re.compile(
    r"dispech|dispatch|spedit|logist|transport|videonab|monitor|ohran|sigurn|security|sot\b|"
    r"operator-(?:na-)?(?:danni|sot|video)|danni|data|annot|moderat|klient|customer|support|"
    r"call|kontakt|fraud|izmam|kyc|proverk|verif|administrat|deloprois|ofis|distanc|ot-doma|ot-vkashti|remote|home"
)

# --- international boards -----------------------------------------------------------------------
HIMALAYAS_QUERIES = [  # (query, country filter)
    ("bulgarian", None),
    ("customer support", "Bulgaria"), ("customer service", "Bulgaria"), ("dispatcher", "Bulgaria"),
    ("logistics coordinator", "Bulgaria"), ("data annotation", "Bulgaria"), ("ai trainer", "Bulgaria"),
    ("transcription", "Bulgaria"), ("content moderator", "Bulgaria"), ("data entry", "Bulgaria"),
    ("fraud", "Bulgaria"), ("kyc", "Bulgaria"), ("monitoring", "Bulgaria"),
]
# Locations that include someone living in Bulgaria.
OPEN_LOCATION_RE = re.compile(
    r"worldwide|anywhere|global|europe|\beu\b|emea|bulgaria|българ|\beet\b|\bcet\b|eastern europe", re.I)
# International titles that fit him, and titles that don't (seniority, specialist professions).
TITLE_OK_RE = re.compile(
    r"customer (?:support|service|care|experience)|support (?:agent|specialist|representative|associate|advisor)|"
    r"call cent|contact cent|dispatch|logistics coordinator|transport coordinator|fleet coordinator|"
    r"annotat|ai trainer|\brater\b|evaluator|transcri|data entry|data label|moderat|trust (?:&|and) safety|"
    r"fraud|\bkyc\b|\baml\b|verification|monitoring operator|security operator|cctv|alarm|back[ -]office",
    re.I,
)
TITLE_BAD_RE = re.compile(
    r"senior|\bsr\b|\blead\b|manager|head of|director|engineer|developer|architect|account executive|sales|"
    r"tier (?:ii|iii|2|3)|principal|scientist|lawyer|attorney|interpreter|nurse|physician|recruiter|"
    r"microsoft dynamics|salesforce|\bsap\b",
    re.I,
)
# "<Domain> Specialist – AI Trainer" gigs need expert knowledge (coding, chemistry, finance...).
AI_EXPERT_RE = re.compile(
    r"(?:specialist|expert|auditor|actor|owners?|ownership|designer|tutoring)\W.*ai trainer|ai task auditor", re.I)

# --- shared text rules --------------------------------------------------------------------------
REMOTE_RE = re.compile(
    r"дистанционна работа|работа от вкъщи|от вкъщи|работа от дома|(?:изцяло|напълно|основно|100%) дистанционн|"
    r"дистанционно от|home[\s-]?office|work(?:ing)? from home|fully remote|100% remote|"
    r"remote (?:work|position|job|role|bulgaria)|\|\s*remote|онлайн работа|работа онлайн",
    re.I,
)
NEGATION_RE = re.compile(r"(?:\bне\b|\bняма\b|\bбез\b|\bno\b|\bnot\b)[^.!?]{0,40}$", re.I)
BULGARIAN_RE = re.compile(r"bulgarian|българск|български", re.I)
HYBRID_RE = re.compile(r"хибрид|hybrid", re.I)
NIGHT_RE = re.compile(r"нощн|night shift", re.I)
US_HOURS_RE = re.compile(r"\b(?:EST|EDT|PST|PDT|CST|CDT)\b|eastern time|pacific time|central time|us time ?zone|usa trucking", re.I)
ENGLISH_RE = re.compile(r"английск|english", re.I)
FLUENT_ENGLISH_RE = re.compile(r"(?:fluent|excellent|native|proficient)[^.]{0,20}english|english[^.]{0,25}\b(?:c1|c2)\b", re.I)
OTHER_LANG_RE = re.compile(
    r"немски|german|френски|french|италиански|italian|испански|spanish|гръцки|greek|турски|turkish|"
    r"португалск|portuguese|словашк|slovak|чешк|czech|полск|polish|холандск|нидерландск|dutch|румънск|romanian|"
    r"руски|russian|унгарск|hungarian|сръбск|serbian|хърватск|croatian|словенск|slovenian|скандинав|шведск|swedish|"
    r"норвежк|norwegian|датск|danish|финск|finnish|arabic|арабск|cantonese|mandarin|chinese|китайск|japanese|"
    r"японск|korean|hindi|vietnamese|thai\b|indonesian|hebrew|ukrainian|украинск",
    re.I,
)

# --- "no special skills" rules ----------------------------------------------------------------
# Titles of specialist jobs (technical, professional, or needing training he doesn't have).
SPECIALIST_TITLE_RE = re.compile(
    r"\bseo\b|\bsem\b|analyst|analytics|technical|tech support|it support|helpdesk|help desk|marketing|copywrit|"
    r"writer|editor|translat|accountant|accounting|bookkeep|financ|compliance|legal|paralegal|teacher|tutor|"
    r"developer|programmer|designer|efficiency expert|trilingual|multilingual|fraud|\baml\b|anti-money|"
    r"аналитик|анализатор|маркетинг|счетовод|финанс|юрист|юридич|програмист|дизайнер|преводач|техническа поддръжка",
    re.I,
)
_SKILLS = (r"sql|python|javascript|html|css|\bapis?\b|\bseo\b|\bsem\b|google analytics|power ?bi|tableau|programming|"
           r"coding|accounting|bookkeeping|statistic\w*|troubleshoot\w*|networking|linux|"
           r"програмиране|счетоводств\w*|статистик\w*")
_NEED = r"experience|knowledge|proficien\w*|familiar\w*|skills?|background|expertise|understanding|опит|познания|умения"
# A technical skill named as a requirement ("experience with SQL", "Python skills"), not just mentioned.
SKILL_REQ_RE = re.compile(rf"(?:{_NEED})\W+(?:\S+\W+){{0,6}}?(?:{_SKILLS})|(?:{_SKILLS})\W+(?:\S+\W+){{0,4}}?(?:{_NEED})", re.I)
# Professional experience in a specialist trade (e.g. "two years of professional transcription").
PRO_TRADE_RE = re.compile(
    r"professional (?:\w+[ ,]+){0,2}?(?:transcription|translation|captioning|court reporting|interpreting|linguistic)", re.I)
DEGREE_FIELD_RE = re.compile(
    r"degree in (?:computer|finance|accounting|economics|law|marketing|engineering|information|data|statistics|"
    r"math|business|linguistics)|висше (?:икономическо|техническо|юридическо) образование", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "една": 1, "две": 2, "три": 3, "четири": 4, "пет": 5}
EXPERIENCE_RE = re.compile(
    r"(\d+|one|two|three|four|five|една|две|три|четири|пет)(?:\s*[-–]\s*\d+)?\s*\+?\s*(?:years?|yrs|години|годин\w*|г\.)"
    r"\s+(?:of\s+)?(?:[\w-]+[\s,]+){0,4}?(?:experience|опит)", re.I)
COMPANY_BOAST_RE = re.compile(
    r"(?:company|business|agency|firm|\bwe\b|\bour\b|фирма|компания)\b[^.]{0,30}?(?:over|more than|над)\s*$", re.I)
PROVEN_EXPERIENCE_RE = re.compile(
    r"proven experience|prior experience (?:is )?required|previous experience (?:in|as|with)|experience (?:is )?required|"
    r"опит на (?:сходна|подобна) позиция|изисква се опит", re.I)
NO_EXPERIENCE_RE = re.compile(
    r"no (?:prior |previous )?experience|without (?:prior )?experience|entry[- ]level|training (?:is )?provided|"
    r"we (?:will )?(?:provide|offer) (?:full |paid )?training|без (?:нужда от )?опит|не се изисква опит|осигурява\w* обучение",
    re.I,
)


def needs_special_skills(title, body):
    """Reason string if the job needs specialised skills, else None."""
    if m := SPECIALIST_TITLE_RE.search(title):
        return f"title: {m.group(0)}"
    if m := SKILL_REQ_RE.search(body):
        return f"skill: {m.group(0)[:60]}"
    if m := PRO_TRADE_RE.search(body):
        return f"trade: {m.group(0)}"
    if m := DEGREE_FIELD_RE.search(body):
        return f"degree: {m.group(0)}"
    return None


ROLE_GROUPS = [
    ("Диспечер / логистика", re.compile(r"диспеч|dispatch|спедит|логист|logistic|транспорт|transport|fleet", re.I)),
    ("Охрана / видеонаблюдение", re.compile(r"видеонаблюд|мониторинг|monitoring|сот\b|охран|security|cctv|alarm|сигнално", re.I)),
    ("Обслужване на клиенти", re.compile(r"клиент|customer|support|кол център|call cent|contact cent|контакт", re.I)),
    ("AI / транскрипция", re.compile(r"annotat|анотац|ai trainer|\brater\b|evaluator|transcri|транскрип|label", re.I)),
    ("Данни / проверка / администрация", re.compile(
        r"данни|data|модерат|moderat|провер|verif|kyc|\baml\b|измам|fraud|trust|администр|деловод|офис|back[ -]office", re.I)),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "bg,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url):
    return json.loads(get(url))


def text_of(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def is_remote(text):
    """True if some remote-work phrase appears without a negation just before it."""
    return any(not NEGATION_RE.search(text[max(0, m.start() - 45):m.start()]) for m in REMOTE_RE.finditer(text))


def mostly_english(text):
    letters = re.findall(r"[a-zA-Zа-яА-Я]", text[:3000])
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.6


def money(lo, hi, cur="", period=""):
    lo = None if lo in (None, "", 0, "0") else lo
    hi = None if hi in (None, "", 0, "0") else hi
    if not (lo or hi):
        return ""
    period = {"yearly": "/год.", "annual": "/год.", "year": "/год.", "MONTH": "/мес.", "monthly": "/мес."}.get(period, "")
    return f"{lo or '?'}–{hi or '?'} {cur}{period}".strip()


def job(source, key, url, title, company="", location="", salary="", posted="", until="", text="", remote=True, kind=""):
    title = re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF]", "", text_of(title)).strip()  # emojis
    return {"source": source, "key": f"{source}:{key}", "url": url, "title": title, "company": company or "",
            "city": location or "", "salary": salary, "posted": posted, "until": until, "text": text, "remote": remote,
            "kind": " ".join(kind) if isinstance(kind, list) else str(kind or "")}


# --- sources ------------------------------------------------------------------------------------

def zaplata(seen, report_all, stats, live, cache=None):
    """Open only ads not seen before. Every listed ad's key goes into `live`, opened or not.

    `cache` (ad id -> JSON-LD) is optional; review tools pass one to avoid refetching on reruns."""
    cache = {} if cache is None else cache
    index = get(ZAPLATA_SITEMAP)
    urls = []
    for m in [u for u in re.findall(r"<loc>([^<]+)</loc>", index) if "sitemap-ads" in u]:
        urls += re.findall(r"<loc>([^<]+)</loc>", get(m))
    ads = []
    for u in urls:
        m = re.match(r"https://www\.zaplata\.bg/([^/]+)/([^/]+)/(\d+)/([^/]+)/", u)
        if m and (m[1] in TARGET_CATS or SLUG_RE.search(m[4])):
            ads.append({"url": u, "id": m[3], "slug": m[4]})
    live.update(f"zaplata.bg:{a['id']}" for a in ads)
    out, fetched = [], 0
    for a in ads:
        if not report_all and f"zaplata.bg:{a['id']}" in seen:
            continue
        if a["id"] not in cache:
            if fetched >= MAX_FETCH:
                continue
            fetched += 1
            try:
                cache[a["id"]] = parse_jsonld(get(a["url"]))
            except Exception:
                stats["errors"].append("zaplata.bg: " + a["url"])
                continue
            finally:
                time.sleep(DELAY)
        d = cache[a["id"]]
        if not d:
            continue
        sal = ((d.get("baseSalary") or {}).get("value") or {})
        text = text_of(d.get("description"))
        out.append(job(
            "zaplata.bg", a["id"], a["url"], d.get("title", a["slug"]),
            company=(d.get("hiringOrganization") or {}).get("name", ""),
            location=((d.get("jobLocation") or {}).get("address") or {}).get("addressLocality", ""),
            salary=money(sal.get("minValue"), sal.get("maxValue"), (d.get("baseSalary") or {}).get("currency", ""),
                         sal.get("unitText", "")),
            posted=d.get("datePosted", ""), until=d.get("validThrough", ""), text=text,
            remote=is_remote(f"{d.get('title', '')} {text}"), kind=d.get("employmentType", ""),
        ))
    stats["zaplata.bg"] = len(ads)
    return out


def parse_jsonld(page):
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    return None


def himalayas(stats):
    out, seen_guids = [], set()
    for q, country in HIMALAYAS_QUERIES:
        params = {"q": q}
        if country:
            params["country"] = country
        for page in (1, 2):
            params["page"] = page
            d = get_json("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode(params))
            time.sleep(DELAY)
            for j in d.get("jobs") or []:
                guid = j.get("guid") or j.get("applicationLink")
                if guid in seen_guids:
                    continue
                seen_guids.add(guid)
                locs = j.get("locationRestrictions") or []
                exp = j.get("expiryDate")
                out.append(job(
                    "Himalayas", guid, guid, j.get("title", ""), company=j.get("companyName", ""),
                    location=", ".join(locs) or "Worldwide",
                    salary=money(j.get("minSalary"), j.get("maxSalary"), j.get("currency") or "", j.get("salaryPeriod") or ""),
                    posted=_ts(j.get("pubDate")), until=_ts(exp),
                    text=text_of(j.get("description") or j.get("excerpt")), kind=j.get("employmentType", ""),
                ))
            if len(d.get("jobs") or []) < 20:
                break
    stats["Himalayas"] = len(out)
    return out


def _ts(v):
    try:
        return datetime.fromtimestamp(int(v), timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return str(v or "")[:10]


def jobicy(stats):
    d = get_json("https://jobicy.com/api/v2/remote-jobs?count=100&geo=bulgaria")
    out = [job("Jobicy", j["id"], j["url"], j.get("jobTitle", ""), company=j.get("companyName", ""),
               location=j.get("jobGeo", ""),
               salary=money(j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency", ""), j.get("salaryPeriod", "")),
               posted=str(j.get("pubDate", ""))[:10], text=text_of(j.get("jobDescription") or j.get("jobExcerpt")),
               kind=j.get("jobType", ""))
           for j in d.get("jobs") or []]
    stats["Jobicy"] = len(out)
    return out


def remoteok(stats):
    d = get_json("https://remoteok.com/api")
    out = [job("Remote OK", j["id"], j["url"], j.get("position", ""), company=j.get("company", ""),
               location=j.get("location") or "", salary=money(j.get("salary_min"), j.get("salary_max"), "USD", "yearly"),
               posted=str(j.get("date", ""))[:10], text=text_of(j.get("description")))
           for j in d if isinstance(j, dict) and j.get("id")]
    stats["Remote OK"] = len(out)
    return out


def workingnomads(stats):
    d = get_json("https://www.workingnomads.com/api/exposed_jobs/")
    out = [job("Working Nomads", j["url"], j["url"], j.get("title", ""), company=j.get("company_name", ""),
               location=j.get("location") or "", posted=str(j.get("pub_date", ""))[:10], text=text_of(j.get("description")))
           for j in d]
    stats["Working Nomads"] = len(out)
    return out


def weworkremotely(stats):
    root = ET.fromstring(get("https://weworkremotely.com/remote-jobs.rss"))
    out = []
    for it in root.iter("item"):
        t = lambda tag: (it.findtext(tag) or "").strip()
        company, _, title = t("title").partition(": ")
        if not title:
            company, title = "", company
        link = t("link") or t("guid")
        out.append(job("We Work Remotely", link, link, title, company=company,
                       location=" ".join(x for x in (t("region"), t("country")) if x),
                       posted=t("pubDate")[5:16], text=text_of(t("description")), kind=t("type")))
    stats["We Work Remotely"] = len(out)
    return out


def remotive(stats):
    d = get_json("https://remotive.com/api/remote-jobs")
    out = [job("Remotive", j["id"], j["url"], j.get("title", ""), company=j.get("company_name", ""),
               location=j.get("candidate_required_location", ""), salary=j.get("salary") or "",
               posted=str(j.get("publication_date", ""))[:10], text=text_of(j.get("description")), kind=j.get("job_type", ""))
           for j in d.get("jobs") or []]
    stats["Remotive"] = len(out)
    return out


# --- effort: how much you need to know, and how much time it takes ------------------------------
PART_TIME_RE = re.compile(
    r"part[- ]?time|непълно работно време|flexible (?:hours|schedule|working hours)|work when(?:ever)? you want|"
    r"choose your (?:own )?(?:hours|schedule)|set your own (?:hours|schedule)|hours (?:may )?vary|"
    r"as (?:many|few|much|little) (?:hours|time)|project[- ]based|per task|гъвкаво работно време|"
    r"свободен график|гъвкав график", re.I)
FULL_TIME_RE = re.compile(
    r"full[- ]?time|пълно работно време|40 hours|(?:monday|mon)\s*(?:to|-|–|through)\s*(?:friday|fri)|"
    r"fixed schedule|8[- ]hour shifts?|8 часа", re.I)
REQ_SIGNAL_RE = re.compile(
    r"\b(?:must|required|requirements?|proficien\w*|experience (?:with|in)|knowledge of|familiar(?:ity)? with|"
    r"ability to|able to|strong|excellent|degree|certif\w*|изисква\w*|познания|умения)\b", re.I)
TOOLS_RE = re.compile(
    r"\b(crm|zendesk|salesforce|freshdesk|intercom|hubspot|asana|slack|jira|trello|google sheets|google docs|"
    r"dialer|ticketing)\b", re.I)


def hours_type(kind, text):
    """'full', 'part' (part-time or flexible hours), 'freelance' (contract, hours not fixed), or '' if unknown.

    A fixed schedule in the text wins over the board's label: many "Contractor" jobs still run Mon-Fri shifts."""
    k = kind.lower().replace("_", " ").replace("-", " ")
    if FULL_TIME_RE.search(text) or ("full" in k and "part" not in k):
        return "full"
    if "part" in k or PART_TIME_RE.search(text):
        return "part"
    if re.search(r"contract|freelance|temporary", k):
        return "freelance"
    return ""


HOURS_LABELS = {"part": "непълно или гъвкаво време", "freelance": "на свободна практика", "full": "пълно работно време"}


def facts(title, body):
    """What the ad asks for, read once; both the warnings and the difficulty score come from this."""
    full = f"{title} {body}"
    # Skip company boasts like "a company with over 10 years of experience".
    years = [n for m in EXPERIENCE_RE.finditer(body)
             if not COMPANY_BOAST_RE.search(body[max(0, m.start() - 60):m.start()])
             and 0 < (n := NUMBER_WORDS.get(m[1].lower()) or int(m[1])) < 20]
    return {
        "years": max(years, default=0),
        "proven": not years and bool(PROVEN_EXPERIENCE_RE.search(body)),
        "english_ad": mostly_english(full),
        "english": "fluent" if FLUENT_ENGLISH_RE.search(full) else "basic" if ENGLISH_RE.search(full) else "",
        "nights": bool(NIGHT_RE.search(full)),
        "us_hours": bool(US_HOURS_RE.search(full)),
        "hybrid": bool(HYBRID_RE.search(full)),
        "no_experience": bool(NO_EXPERIENCE_RE.search(full)),
    }


def warnings(f, countries_given):
    flags = []
    if f["years"]:
        flags.append(f"изисква {f['years']}+ г. опит")
    elif f["proven"]:
        flags.append("изисква опит")
    if f["english_ad"]:
        flags.append("обявата е на английски")
    if f["english"] == "fluent":
        flags.append("изисква отличен английски")
    elif f["english"] == "basic" and not f["english_ad"]:
        flags.append("изисква английски")
    if f["nights"]:
        flags.append("има нощни смени")
    if f["us_hours"]:
        flags.append("работа по американско време, проверете часовете")
    if f["hybrid"]:
        flags.append("хибридна")
    if not countries_given:
        flags.append("не е посочено от кои държави")
    return flags


def effort(f, title, body, kind):
    """Score how hard a job is to get and do: lower is easier. Returns (score, level, hours)."""
    full = f"{title} {body}"
    score = -2.0 if f["no_experience"] else 0.0
    score += min(f["years"], 5) if f["years"] else 1.5 if f["proven"] else 0
    # An English ad implies English; only an explicit "fluent" asks more than the rest of its section.
    score += 2 if f["english"] == "fluent" else 1 if f["english"] == "basic" and not f["english_ad"] else 0
    score += min(len(REQ_SIGNAL_RE.findall(body)), 15) * 0.2
    score += min(len({t.lower() for t in TOOLS_RE.findall(full)}) * 0.5, 2)
    hours = hours_type(kind, full)
    score += {"part": -1.5, "freelance": -1, "full": 2, "": 0}[hours]
    score += f["nights"] + f["us_hours"]
    level = "Лесна" if score <= 1.5 else "Средна" if score <= 4 else "По-трудна"
    return round(score, 1), level, hours


# --- filtering ----------------------------------------------------------------------------------

def analyse(j):
    """Return the job with roles/flags added, or None if it doesn't suit him."""
    title, body = j["title"], j["text"]
    full = f"{title} {body}"
    bulgarian = j["source"] == "zaplata.bg" and not mostly_english(full) or bool(BULGARIAN_RE.search(full))
    if j["source"] == "zaplata.bg":
        if not j["remote"]:
            return None
        roles = [n for n, rx in ROLE_GROUPS if rx.search(title)] or [n for n, rx in ROLE_GROUPS if rx.search(body[:1500])]
        if not roles:
            return None
    else:
        loc = j["city"]
        if loc and not OPEN_LOCATION_RE.search(loc):
            return None
        bg_title = bool(BULGARIAN_RE.search(title))
        if TITLE_BAD_RE.search(title) or not (bg_title or TITLE_OK_RE.search(title)):
            return None
        if AI_EXPERT_RE.search(title) and not bg_title:
            return None
        roles = [n for n, rx in ROLE_GROUPS if rx.search(title)]
    if OTHER_LANG_RE.search(title) or (not BULGARIAN_RE.search(full) and OTHER_LANG_RE.search(body[:2500])):
        return None
    if needs_special_skills(title, body):
        return None
    f = facts(title, body)
    r = {k: v for k, v in j.items() if k != "text"}
    r.update(roles=roles, flags=warnings(f, j["city"] or j["source"] == "zaplata.bg"), bulgarian=bulgarian,
             no_experience=f["no_experience"])
    r["effort"], r["level"], r["hours"] = effort(f, title, body, j.get("kind", ""))
    return r


def fmt(r):
    bits = [f"**[{r['title']}]({r['url']})** ({r['source']})"]
    meta = [x for x in (r["company"], r["city"], r["salary"]) if x]
    if meta:
        bits.append(" · ".join(meta))
    hours = HOURS_LABELS.get(r.get("hours"), "")
    bits.append(f"Трудност: {r.get('level', '?')}" + (f", {hours}" if hours else ""))
    if r.get("no_experience"):
        bits.append("✓ подходяща без опит")
    if r["roles"]:
        bits.append("Тип: " + ", ".join(r["roles"]))
    if r["flags"]:
        bits.append("⚠ " + ", ".join(r["flags"]))
    if r["until"]:
        bits.append(f"До: {r['until']}")
    return "- " + "  \n  ".join(bits)


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data, **kw):
    path.write_text(json.dumps(data, ensure_ascii=False, **kw), encoding="utf-8")


def update_active(active, found, ok, live, today):
    """Keep jobs.json to the matching jobs still listed on their site.

    A job is dropped when its site was checked and no longer lists it, or its deadline passed.
    Jobs from a site that failed today are kept as they were."""
    for k, r in list(active.items()):
        if (r["source"] in ok and k not in live) or (r["until"] and r["until"][:10] < today):
            del active[k]
        elif r["source"] in ok:
            r["last_seen"] = today
    for r in found:
        r["first_seen"] = active.get(r["key"], {}).get("first_seen", today)
        r["last_seen"] = today
        active[r["key"]] = r


def seed_active():
    """First run with live tracking: start from the jobs in earlier daily reports."""
    active = {}
    for p in sorted(REPORTS.glob("*.json")):
        rep = load(p, {})
        for s in rep.get("sections", []):
            for r in s["jobs"]:
                active.setdefault(r["key"], {**r, "first_seen": rep["date"], "last_seen": rep["date"]})
    return active


def main():
    report_all = "--all" in sys.argv
    DATA.mkdir(parents=True, exist_ok=True)
    seen = load(STATE, {})
    active = load(ACTIVE, None)
    if active is None:
        active = seed_active()
    stats, live, ok, jobs = {"errors": []}, set(), set(), []
    for name, fn in [("zaplata.bg", lambda: zaplata(seen, report_all, stats, live)), ("Himalayas", lambda: himalayas(stats)),
                     ("Jobicy", lambda: jobicy(stats)), ("Remote OK", lambda: remoteok(stats)),
                     ("Working Nomads", lambda: workingnomads(stats)), ("We Work Remotely", lambda: weworkremotely(stats)),
                     ("Remotive", lambda: remotive(stats))]:
        try:
            got = fn()
        except Exception as e:
            stats["errors"].append(f"{name}: {type(e).__name__}: {e}")
            continue
        ok.add(name)
        live.update(j["key"] for j in got)
        jobs += got
    if not ok:
        sys.exit("Всички източници са недостъпни: " + "; ".join(stats["errors"]))

    now = datetime.now(TZ)
    today = now.date().isoformat()
    found, keys = [], set()
    for j in jobs:
        if j["key"] in keys or (not report_all and j["key"] in seen):
            continue
        keys.add(j["key"])
        seen.setdefault(j["key"], today)
        r = analyse(j)
        if r:
            found.append(r)
    # Forget jobs their site no longer lists, once they are old enough not to come back.
    cutoff = (now.date() - timedelta(days=SEEN_DAYS)).isoformat()
    for k in [k for k, d in seen.items() if d < cutoff and k not in live and k.split(":", 1)[0] in ok]:
        del seen[k]
    save(STATE, seen)
    update_active(active, found, ok, live, today)
    save(ACTIVE, active, indent=1)

    # A second run on the same day adds to that day's report instead of replacing it.
    prev = load(REPORTS / f"{today}.json", None)
    if prev and not report_all:
        known = {r["key"] for r in found}
        found += [r for s in prev["sections"] for r in s["jobs"] if r["key"] not in known]

    order =lambda r: (r["effort"], r["title"])  # easiest first
    bg = sorted([r for r in found if r["bulgarian"]], key=order)
    other = sorted([r for r in found if not r["bulgarian"]], key=order)
    sections = [{"title": "На български или търсят български език", "jobs": bg},
                {"title": "Други дистанционни обяви (на английски)", "jobs": other}]
    sources = {k: v for k, v in stats.items() if k != "errors"}

    lines = [f"# Нови дистанционни обяви — {today}", "",
             "Източници: " + ", ".join(f"{k} ({v})" for k, v in sources.items()) + ". "
             "Пропуснати са обяви, които изискват специални или технически умения или езици освен български и английски.", ""]
    if stats["errors"]:
        lines += ["Грешки: " + "; ".join(stats["errors"][:5]), ""]
    for s in sections:
        lines += [f"## {s['title']} ({len(s['jobs'])})", ""]
        lines += [fmt(r) for r in s["jobs"]] or ["Няма нови."]
        lines.append("")
    report = "\n".join(lines)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{today}.md").write_text(report, encoding="utf-8")
    data = {"date": today, "checked": now.isoformat(timespec="minutes"), "sources": sources, "errors": stats["errors"],
            "sections": sections}
    save(REPORTS / f"{today}.json", data, indent=1)
    build_page.build(DATA, SITE)
    print(report)
    print(f"\nАктуални обяви: {len(active)}. Страница: {SITE / 'index.html'}")


if __name__ == "__main__":
    main()
