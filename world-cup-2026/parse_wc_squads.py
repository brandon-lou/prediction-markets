#!/usr/bin/env python3
"""
Parse Wikipedia WC squads pages (2006–2026) to compute per-team:
  - Squad average age at tournament start date
  - Average international caps per squad
  - Count of players at UEFA CL group-stage clubs (season preceding each WC)

Uses the Wikipedia API section-by-section (full pages are too large to fetch).

Run:
    python3 parse_wc_squads.py

Copy the "FINAL PYTHON OUTPUT" block it prints into the data files:
  2006–2022 data → wc_historical_data.py (training covariates)
  2026 data      → covariates_2026.py  (prediction inputs)
"""
import urllib.request
import urllib.parse
import json
import re
import time
from datetime import date

WC_CONFIG = [
    (2006, date(2006, 6, 9),   "2006_FIFA_World_Cup_squads"),
    (2010, date(2010, 6, 11),  "2010_FIFA_World_Cup_squads"),
    (2014, date(2014, 6, 12),  "2014_FIFA_World_Cup_squads"),
    (2018, date(2018, 6, 14),  "2018_FIFA_World_Cup_squads"),
    (2022, date(2022, 11, 20), "2022_FIFA_World_Cup_squads"),
    (2026, date(2026, 6, 11),  "2026_FIFA_World_Cup_squads"),
]

# Set to a list of years to run only those, e.g. [2026] or [2022, 2026].
# None = run all years in WC_CONFIG.
RUN_YEARS = [2026]

TEAM_NAME_FIXES = {
    "Côte d'Ivoire":            "Ivory Coast",
    "Korea Republic":            "South Korea",
    "Korea DPR":                 "North Korea",
    "Bosnia-Herzegovina":        "Bosnia and Herzegovina",
    "Bosnia &amp; Herzegovina":  "Bosnia and Herzegovina",
    "Bosnia &#038; Herzegovina": "Bosnia and Herzegovina",
    # 2026 WC page variants
    "United States":             "United States",  # keep consistent
    "Czechia":                   "Czech Republic",
    "DR Congo":                  "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    "Curaçao":                   "Curaçao",
}

KNOWN_AGES = {
    2006: {
        "Italy": 28.80, "England": 27.40, "Trinidad and Tobago": 27.80,
        "Germany": 27.10, "Costa Rica": 27.20, "Sweden": 26.90,
        "Poland": 26.80, "Paraguay": 26.40, "Ecuador": 26.30, "Ghana": 24.60,
    },
    2010: {
        "Brazil": 28.6, "England": 28.4, "Australia": 28.4, "Italy": 28.2,
        "Paraguay": 28.1, "Honduras": 28.0, "Portugal": 27.8, "Japan": 27.8,
        "Greece": 27.7, "Netherlands": 27.7, "Denmark": 27.6, "France": 27.4,
        "South Korea": 27.4, "Mexico": 27.1, "Argentina": 27.1,
        "South Africa": 27.0, "United States": 26.8, "Ivory Coast": 26.7,
        "Slovenia": 26.7, "Switzerland": 26.7, "New Zealand": 26.5,
        "Algeria": 26.3, "Uruguay": 26.1, "Serbia": 26.0, "Slovakia": 26.0,
        "Spain": 25.9, "Chile": 25.9, "Nigeria": 25.9, "Cameroon": 25.2,
        "Germany": 25.0, "North Korea": 24.7, "Ghana": 24.0,
    },
    2014: {
        "Argentina": 28.92, "Honduras": 28.57, "Uruguay": 28.55,
        "Portugal": 28.53, "Iran": 28.49, "Greece": 28.49, "Brazil": 28.36,
        "Spain": 28.25, "Chile": 27.99, "Russia": 27.98, "Italy": 27.90,
        "Colombia": 27.87, "Mexico": 27.26, "Japan": 27.23, "Croatia": 27.18,
        "France": 27.09, "Bosnia and Herzegovina": 27.05, "Cameroon": 26.62,
        "Algeria": 26.61, "England": 26.57, "Netherlands": 26.47,
        "Australia": 26.36, "Germany": 26.31, "Ghana": 24.90,
    },
    2018: {
        "Argentina": 29.0, "Mexico": 28.9, "Costa Rica": 28.5, "Egypt": 28.4,
        "Panama": 28.4, "Russia": 28.3, "Japan": 28.3, "Iceland": 28.1,
        "Saudi Arabia": 28.1, "Brazil": 28.1, "Spain": 28.0, "Portugal": 27.9,
        "Colombia": 27.9, "Poland": 27.9, "Uruguay": 27.7, "Sweden": 27.7,
        "Australia": 27.6, "Croatia": 27.4, "South Korea": 27.3,
        "Belgium": 27.1, "Peru": 27.0, "Morocco": 26.8, "Denmark": 26.7,
        "Switzerland": 26.7, "Iran": 26.7, "Senegal": 26.7, "Germany": 26.7,
        "Serbia": 26.3, "Tunisia": 26.0, "England": 26.0, "France": 25.6,
        "Nigeria": 25.5,
    },
    2022: {
        "Iran": 28.9, "Mexico": 28.5, "Argentina": 27.9, "Brazil": 27.8,
        "Tunisia": 27.8, "Belgium": 27.8, "Uruguay": 27.8, "Japan": 27.8,
        "South Korea": 27.7, "Australia": 27.5, "France": 26.6,
        "England": 26.4, "Morocco": 26.3, "Wales": 26.3, "Cameroon": 26.3,
        "Senegal": 26.2, "Ecuador": 25.6, "Spain": 25.6,
        "United States": 25.2, "Ghana": 24.7,
    },
}

# ── UEFA CL group-stage clubs (season preceding each WC) ─────────────────────
# Values are sets of display names as they appear in Wikipedia squad-page wikilinks
# (e.g. [[FC Bayern Munich|Bayern Munich]] → "Bayern Munich").
# Aliases cover the most common alternate forms found in those pages.

CL_CLUBS = {
    2006: {  # 2005-06 UCL
        "Barcelona", "Real Madrid", "Villarreal",
        "Juventus", "AC Milan", "Inter Milan", "Internazionale",
        "Chelsea", "Arsenal", "Liverpool", "Manchester United",
        "Bayern Munich", "PSV Eindhoven", "PSV",
        "Ajax", "Benfica", "Porto",
        "Lyon", "Olympique Lyonnais",
        "Werder Bremen", "Schalke 04",
        "Club Brugge", "Bruges",
        "Rapid Vienna", "Rapid Wien",
        "Panathinaikos", "Rangers", "Artmedia Bratislava",
        "Thun", "Udinese", "Anderlecht", "Rosenborg",
        "CSKA Moscow", "CSKA",
        "Fenerbahçe", "Fenerbahce",
        "Sparta Prague", "Olympiacos", "Olympiakos",
    },
    2010: {  # 2009-10 UCL
        "Barcelona", "Inter Milan", "Internazionale",
        "Bayern Munich", "Manchester United",
        "Liverpool", "AC Milan", "Chelsea", "Real Madrid",
        "Marseille", "Olympique de Marseille",
        "Porto", "Sevilla",
        "Wolfsburg", "VfL Wolfsburg",
        "Arsenal",
        "CSKA Moscow", "CSKA",
        "Lyon", "Olympique Lyonnais",
        "Bordeaux", "Girondins de Bordeaux",
        "Fiorentina",
        "Beşiktaş", "Besiktas",
        "Debrecen", "Unirea Urziceni",
        "Atlético Madrid", "Atletico Madrid",
        "Juventus", "Rubin Kazan",
        "Panathinaikos",
        "AZ Alkmaar", "AZ",
        "Olympiacos", "Olympiakos",
        "Standard Liège", "Standard Liege",
        "Rangers",
        "APOEL", "Apoel Nicosia",
        "Stuttgart", "VfB Stuttgart",
    },
    2014: {  # 2013-14 UCL
        "Bayern Munich", "Atlético Madrid", "Atletico Madrid",
        "Chelsea", "Real Madrid",
        "Borussia Dortmund", "Paris Saint-Germain", "PSG",
        "Manchester City", "Juventus", "Barcelona",
        "Arsenal", "Manchester United",
        "Porto", "Schalke 04", "AC Milan", "Benfica",
        "Shakhtar Donetsk",
        "BATE Borisov", "Galatasaray",
        "Viktoria Plzeň", "Viktoria Plzen",
        "Anderlecht", "Celtic",
        "Olympiacos", "Olympiakos",
        "Napoli", "SSC Napoli",
        "Zenit Saint Petersburg", "Zenit",
        "CSKA Moscow", "CSKA",
        "Basel",
        "Real Sociedad",
        "Steaua București", "Steaua Bucharest",
        "Bayer Leverkusen", "Leverkusen",
        "Marseille", "Ajax",
        "Wolfsburg", "VfL Wolfsburg",
    },
    2018: {  # 2017-18 UCL
        "Real Madrid", "Chelsea", "Barcelona",
        "Tottenham Hotspur", "Tottenham",
        "Atlético Madrid", "Atletico Madrid",
        "Manchester City", "Bayern Munich", "Manchester United",
        "Paris Saint-Germain", "PSG",
        "Juventus", "Sevilla", "Liverpool",
        "Roma", "AS Roma",
        "Borussia Dortmund",
        "Basel", "Benfica", "Porto",
        "RB Leipzig", "Leipzig",
        "Napoli", "SSC Napoli",
        "Shakhtar Donetsk",
        "CSKA Moscow", "CSKA",
        "Spartak Moscow",
        "Anderlecht", "Celtic", "Feyenoord",
        "Maribor",
        "Qarabağ", "Qarabag",
        "Sporting CP", "Sporting Lisbon",
        "Olympiacos", "Olympiakos",
        "Beşiktaş", "Besiktas",
        "APOEL",
    },
    2022: {  # 2021-22 UCL
        "Chelsea", "Real Madrid", "Barcelona", "Sevilla",
        "Manchester City", "Manchester United",
        "Liverpool", "Bayern Munich",
        "Borussia Dortmund",
        "Inter Milan", "Internazionale",
        "AC Milan", "Atalanta",
        "Juventus", "Paris Saint-Germain", "PSG",
        "Ajax", "Benfica", "Porto",
        "Atlético Madrid", "Atletico Madrid",
        "Shakhtar Donetsk",
        "RB Leipzig", "Leipzig",
        "Villarreal",
        "Sporting CP", "Sporting Lisbon",
        "Salzburg", "RB Salzburg", "Red Bull Salzburg",
        "Sheriff Tiraspol", "Sheriff",
        "Club Brugge", "Bruges",
        "Young Boys",
        "Wolfsburg", "VfL Wolfsburg",
        "Beşiktaş", "Besiktas",
        "Dynamo Kyiv", "Dynamo Kiev",
        "Zenit Saint Petersburg", "Zenit",
        "Malmö", "Malmo", "Malmö FF",
        "Lille", "LOSC Lille",
    },
    2026: {  # 2025-26 UCL (36-club league phase, new format)
        # Source: UEFA / Al Jazeera confirmed participant list
        "Ajax", "Arsenal",
        "Atalanta",
        "Athletic Club", "Athletic Bilbao",
        "Atlético Madrid", "Atletico Madrid",
        "Borussia Dortmund", "Dortmund",
        "Barcelona",
        "Bayern Munich", "Bayern München",
        "Benfica",
        "Bodø/Glimt", "Bodo/Glimt",
        "Chelsea",
        "Club Brugge", "Bruges",
        "Copenhagen", "FC Copenhagen",
        "Frankfurt", "Eintracht Frankfurt",
        "Galatasaray",
        "Inter Milan", "Inter", "Internazionale",
        "Juventus",
        "Kairat Almaty", "Kairat",
        "Bayer Leverkusen", "Leverkusen",
        "Liverpool",
        "Manchester City", "Man City",
        "Marseille", "Olympique de Marseille",
        "Monaco", "AS Monaco",
        "Napoli", "SSC Napoli",
        "Newcastle United", "Newcastle",
        "Olympiacos", "Olympiakos",
        "Pafos", "FC Pafos",
        "Paris Saint-Germain", "PSG", "Paris",
        "PSV Eindhoven", "PSV",
        "Qarabağ", "Qarabag",
        "Real Madrid",
        "Slavia Praha", "Slavia Prague",
        "Sporting CP", "Sporting Lisbon",
        "Tottenham Hotspur", "Tottenham",
        "Union Saint-Gilloise", "Union SG",
        "Villarreal",
    },
}


# ── Wikipedia API helpers ──────────────────────────────────────────────────────

HEADERS = {"User-Agent": "WC-Squads-Parser/1.0 (academic research)"}

def api_get(url, retries=5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            wait = 15 * (attempt + 1)
            print(f"#     [HTTP {e.code}] waiting {wait}s …", flush=True)
            time.sleep(wait)
        except Exception as e:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"#     [{type(e).__name__}: {e}] retry in {wait}s …", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Failed after {retries} attempts: {url}")

def get_sections(page):
    url = (f"https://en.wikipedia.org/w/api.php?action=parse"
           f"&page={urllib.parse.quote(page)}&prop=sections&format=json")
    data = api_get(url)["parse"]["sections"]
    time.sleep(1.5)
    return data

def get_wikitext(page, idx):
    url = (f"https://en.wikipedia.org/w/api.php?action=parse"
           f"&page={urllib.parse.quote(page)}&section={idx}&prop=wikitext&format=json")
    data = api_get(url)["parse"]["wikitext"]["*"]
    time.sleep(1.0)
    return data


# ── Parsing helpers ────────────────────────────────────────────────────────────

def age_at(dob, ref):
    return (ref - dob).days / 365.25

# FORMAT A — 2006: {{National football squad player|...|
#   age={{birth date and age2|[df=y|]REF_Y|REF_M|REF_D|B_Y|B_M|B_D}}|
#   caps=N|club=[[Club]]|clubnat=...}}
# Birth date is the LAST three positional args; caps/club are named params.
DOB2_RE = re.compile(
    r'\{\{birth date and age2\s*\|(?:[^|=\d][^|]*)?\|?'
    r'\d{4}\|\d{1,2}\|\d{1,2}\|'
    r'(\d{4})\|(\d{1,2})\|(\d{1,2})',
    re.IGNORECASE,
)

# FORMAT B — 2010-2022: wikitable cells
#   || {{birth date and age|Y|M|D}} || N || [[Club]] ||
# Handles: birth date and age, birth date, dob, birth-date and age (hyphen variant).
DOB1_RE = re.compile(
    r'\{\{(?:birth[ -]date(?:[ -]and[ -]age)?|dob)\s*'
    r'\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})',
    re.IGNORECASE,
)

# Cell separator: || or start-of-line |  (not || at start, which is ||)
CELL_SEP = re.compile(r'\|\||\n\s*\|(?!\|)')

# Caps in a cell: optional sort key, optional bold, digits, optional bold.
# Handles: || 86 ||  ||  '''86''' ||  || data-sort-value="86" | '''86''' ||
CAPS_RE = re.compile(
    r'(?:\|\||\n\s*\|(?!\|))\s*'
    r'(?:data-sort-value="[^"]*"\s*\|\s*)?'
    r"'{0,3}\s*(\d+)\s*'{0,3}"
    r'(?=\s*(?:\|\||\n|$))',
)

# Club from |club=...| named param (Format A)
CLUB_NAMED_RE = re.compile(
    r'\|club=(?:\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|([^|{}\n\]]+))',
)

# Flag / icon templates to strip when extracting club names
FLAG_RE = re.compile(
    r'\{\{(?:flag[^}]*|fb[^}]*|flagicon[^}]*|Football[^}]*|sfn[^}]*)\}\}\s*',
    re.IGNORECASE,
)


def extract_wikilink_display(text):
    """Return display name from [[Article|Display]] or [[Article]], else None."""
    m = re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', text)
    if not m:
        return None
    return (m.group(2) or m.group(1)).strip()


def extract_club_cell(window):
    """
    Extract club name from a window that begins just AFTER the caps cell content.
    Looks for the next cell separator, then extracts the club from that cell.
    """
    sep = CELL_SEP.search(window)
    if not sep:
        return None
    cell = window[sep.end() : sep.end() + 200]
    cell = FLAG_RE.sub('', cell)
    # Prefer wikilink display name
    name = extract_wikilink_display(cell)
    if name:
        return name
    # Plain text fallback
    cell = re.sub(r'\{\{[^}]*\}\}', '', cell)
    cell = re.sub(r"'{2,}", '', cell)
    plain = re.split(r'\|\||\n|\|', cell)[0].strip()
    return plain if plain and plain not in ('–', '-', '') else None


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_squad(wikitext, ref_date, cl_clubs):
    """
    Returns (avg_age, avg_caps, cl_count, clubs_list, n).
    avg_age/avg_caps/cl_count are None if n < 5.
    clubs_list is the raw list of extracted club names (for verification).
    """
    ages, caps_list, clubs = [], [], []

    # ── Format A (2006) ────────────────────────────────────────────────────────
    for m in DOB2_RE.finditer(wikitext):
        try:
            dob = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        ages.append(age_at(dob, ref_date))

        brace_end = wikitext.find('}}', m.end())
        if brace_end == -1:
            continue
        # Large window: covers |caps=N|club=[[...]]|clubnat=...}} in outer template
        window = wikitext[brace_end + 2 : brace_end + 400]

        cap_m = re.search(r'\|caps=(\d+)', window)
        if cap_m:
            caps_list.append(int(cap_m.group(1)))

        club_m = CLUB_NAMED_RE.search(window)
        if club_m:
            # group 2 = display name, group 1 = article name, group 3 = plain text
            raw = (club_m.group(2) or club_m.group(1) or club_m.group(3) or '').strip()
            if raw and raw not in ('–', '-', ''):
                clubs.append(raw)

    # ── Format B (2010-2022) ────────────────────────────────────────────────────
    if not ages:
        for m in DOB1_RE.finditer(wikitext):
            try:
                dob = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            ages.append(age_at(dob, ref_date))

            brace_end = wikitext.find('}}', m.end())
            if brace_end == -1:
                continue
            window = wikitext[brace_end + 2 : brace_end + 400]

            # Caps cell (next cell after DOB; handles bold and sort-value markup)
            cap_m = CAPS_RE.search(window)
            if cap_m:
                caps_list.append(int(cap_m.group(1)))
                # Club is the cell AFTER caps — start search from end of caps match
                club = extract_club_cell(window[cap_m.end():])
            else:
                # Caps missing; try to get club from the second cell separator anyway
                first_sep = CELL_SEP.search(window)
                if first_sep:
                    club = extract_club_cell(window[first_sep.end():])
                else:
                    club = None

            if club:
                clubs.append(club)

    n = len(ages)
    if n < 5:
        return None, None, None, clubs, n

    avg_age  = round(sum(ages) / n, 2)
    avg_caps = round(sum(caps_list) / len(caps_list), 1) if caps_list else None
    cl_count = sum(1 for c in clubs if c in cl_clubs) if clubs else None
    return avg_age, avg_caps, cl_count, clubs, n


# ── Section processing ─────────────────────────────────────────────────────────

SKIP_NAMES = {
    'Squads', 'References', 'External links', 'See also', 'Notes',
    'FIFA', 'UEFA', 'Introduction', 'Background', 'Statistics',
    # statistics appendix subsections (present in all WC squad pages)
    'Age', 'Players', 'Outfield players', 'Goalkeeper', 'Goalkeepers', 'Captains',
    'Coaches', 'Player statistics',
    'Player representation by age',
    'Player representation by league', 'Player representation by league system',
    'Player representation by club', 'Player representation by club confederation',
    'Player representation by confederation',
    'Coaches representation by country',
    'Average age of squads',
    'Most capped players', 'Youngest players', 'Oldest players',
}

def normalize_name(raw):
    name = re.sub(r'<[^>]+>', '', raw).strip()
    name = (name.replace('&amp;', '&')
                .replace('&#038;', '&')
                .replace('&#39;', "'")
                .replace('&nbsp;', ' '))
    return TEAM_NAME_FIXES.get(name, name)

def process_year(year, ref_date, page):
    print(f"\n# {'='*60}", flush=True)
    print(f"# {year} WC (start {ref_date})", flush=True)

    sections = get_sections(page)

    print(f"# Sections found ({len(sections)} total):", flush=True)
    for s in sections:
        print(f"#   level={s['toclevel']} idx={s['index']:>3}  {normalize_name(s['line'])}", flush=True)

    team_sections = {}
    for s in sections:
        level = int(s['toclevel'])
        name  = normalize_name(s['line'])
        if re.match(r'^Group [A-Z]$', name, re.I) or name in SKIP_NAMES:
            continue
        if level in (2, 3):
            team_sections[name] = s['index']

    print(f"# → {len(team_sections)} team sections identified", flush=True)

    cl_clubs = CL_CLUBS.get(year, set())
    ages_out, caps_out, cl_out, clubs_out = {}, {}, {}, {}
    known = KNOWN_AGES.get(year, {})
    # Expected squad size: 23 for 2006-2018, 26 for 2022+
    expected_n = 26 if year >= 2022 else 23

    for team in sorted(team_sections, key=lambda t: str(team_sections[t])):
        idx = team_sections[team]
        try:
            wikitext = get_wikitext(page, idx)
            avg_age, avg_caps, cl_count, clubs, n = parse_squad(wikitext, ref_date, cl_clubs)

            if avg_age is None:
                n_a = len(DOB2_RE.findall(wikitext))
                n_b = len(DOB1_RE.findall(wikitext))
                print(f"#   {team:32s}: FAILED n={n}  "
                      f"(fmt-A: {n_a}, fmt-B: {n_b})", flush=True)
                snippet = repr(wikitext[:500]).replace('\\n', '\n#     ')
                print(f"#     wikitext snippet:\n#     {snippet}", flush=True)
                ages_out[team] = caps_out[team] = cl_out[team] = None
                clubs_out[team] = []
                continue

            ages_out[team]  = avg_age
            caps_out[team]  = avg_caps
            cl_out[team]    = cl_count
            clubs_out[team] = clubs

            age_note = ""
            if team in known:
                diff = abs(avg_age - known[team])
                age_note = (f"  ✓ (ref={known[team]:.2f}, Δ={diff:.2f})" if diff < 0.5
                            else f"  ⚠ MISMATCH ref={known[team]:.2f}, Δ={diff:.2f}")
            n_warn = f"  ⚠ EXPECTED {expected_n}" if n != expected_n else ""
            print(f"#   {team:32s}: age={avg_age:.2f}, caps={avg_caps}, "
                  f"cl={cl_count}, n={n}{n_warn}{age_note}", flush=True)

        except Exception as e:
            ages_out[team] = caps_out[team] = cl_out[team] = None
            clubs_out[team] = []
            print(f"#   {team:32s}: ERROR — {e}", flush=True)

    return ages_out, caps_out, cl_out, clubs_out


# ── Main ──────────────────────────────────────────────────────────────────────

all_ages:  dict = {}
all_caps:  dict = {}
all_cl:    dict = {}
all_clubs: dict = {}

for year, ref_date, page in WC_CONFIG:
    if RUN_YEARS is not None and year not in RUN_YEARS:
        continue
    ages, caps, cl, clubs = process_year(year, ref_date, page)
    all_ages[year]  = ages
    all_caps[year]  = caps
    all_cl[year]    = cl
    all_clubs[year] = clubs
    time.sleep(5.0)


# ── Final output ───────────────────────────────────────────────────────────────

print("\n\n# ============================================================")
print("# FINAL PYTHON OUTPUT — copy into wc_historical_data.py / covariates_2026.py")
print("# ============================================================")

print("\nWC_SQUAD_AGE_PARSED = {")
for year in sorted(all_ages):
    d = all_ages[year]
    print(f"    {year}: {{")
    for team in sorted(d):
        v = d[team]
        print(f'        "{team}": {f"{v:.2f}" if v is not None else "None"},')
    print("    },")
print("}")

print("\nWC_SQUAD_CAPS_PARSED = {")
for year in sorted(all_caps):
    d = all_caps[year]
    print(f"    {year}: {{")
    for team in sorted(d):
        v = d[team]
        print(f'        "{team}": {f"{v:.1f}" if v is not None else "None"},')
    print("    },")
print("}")

print("\nWC_SQUAD_CL = {")
for year in sorted(all_cl):
    d = all_cl[year]
    print(f"    {year}: {{")
    for team in sorted(d):
        v = d[team]
        print(f'        "{team}": {v if v is not None else "None"},')
    print("    },")
print("}")

# Club list is for verification/debugging — not written to wc_historical_data.py directly
print("\n# ── Raw club lists (for verifying CL extraction) ──")
print("# WC_SQUAD_CLUBS = {")
for year in sorted(all_clubs):
    d = all_clubs[year]
    print(f"#     {year}: {{")
    for team in sorted(d):
        clubs = d[team]
        print(f'#         "{team}": {clubs},')
    print("#     },")
print("# }")
