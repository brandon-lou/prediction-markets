"""
Covariate data for the 48 WC 2026 teams, to be used as features in the RF extension.

Sources:
  - GDP:        World Bank API, NY.GDP.MKTP.CD, 2024 values (USD)
  - Population: World Bank API, SP.POP.TOTL, 2023 values
  - FIFA rank:  FIFA Men's World Ranking, June 11 2026 release (top 20 confirmed;
                remaining positions are estimates based on public ranking info —
                replace with official data for production use)
  - Squad value: Transfermarkt (EUR millions); all 48 teams confirmed from the
                 Transfermarkt 2026 FIFA World Cup participants page.
  - Squad age:   Transfermarkt ø-Age; all 48 teams confirmed from the same page.
  - Pre-tournament odds: BetMGM American moneyline, recorded before June 11 2026.
                Source: Yahoo Sports / BetMGM, pre-draw and pre-tournament lines.
                https://sports.yahoo.com/soccer/betting/article/2026-world-cup-betting-odds-for-all-48-teams-to-win-the-title-145427136.html

Scotland/England population: not in World Bank (sub-national); using estimates
  Scotland ≈ 5.5M,  England ≈ 57M
"""

# squad_age / squad_caps / squad_cl: parse_wc_squads.py (Wikipedia, age at Jun 11 2026)
# squad_value: Transfermarkt (EUR millions, confirmed all 48 teams)
TEAM_COVARIATES = {
    # --- Group A ---
    "Mexico":                  dict(fifa_rank=14, gdp=1_856_365_616_166, pop=129_739_759, squad_value=191.9,  squad_age=27.90, squad_caps=46.7, squad_cl=1),
    "South Korea":             dict(fifa_rank=22, gdp=1_875_388_209_407, pop=51_712_619,  squad_value=139.1,  squad_age=28.07, squad_caps=36.8, squad_cl=2),
    "South Africa":            dict(fifa_rank=62, gdp=401_144_998_374,   pop=63_212_384,  squad_value=49.3,   squad_age=26.81, squad_caps=18.6, squad_cl=0),
    "Czech Republic":          dict(fifa_rank=38, gdp=330_000_000_000,   pop=10_900_000,  squad_value=188.2,  squad_age=27.62, squad_caps=27.8, squad_cl=12),  # GDP estimated

    # --- Group B ---
    "Canada":                  dict(fifa_rank=27, gdp=2_243_636_826_634, pop=40_083_484,  squad_value=198.7,  squad_age=26.97, squad_caps=36.7, squad_cl=5),
    "Switzerland":             dict(fifa_rank=19, gdp=936_564_198_049,   pop=8_888_822,   squad_value=332.5,  squad_age=28.31, squad_caps=43.5, squad_cl=4),
    "Qatar":                   dict(fifa_rank=68, gdp=219_162_637_363,   pop=2_656_032,   squad_value=19.9,   squad_age=29.51, squad_caps=54.7, squad_cl=0),
    "Bosnia and Herzegovina":  dict(fifa_rank=55, gdp=29_613_572_023,    pop=3_185_073,   squad_value=146.4,  squad_age=26.46, squad_caps=23.0, squad_cl=4),

    # --- Group C ---
    "Brazil":                  dict(fifa_rank=6,  gdp=2_185_821_648_944, pop=211_140_729, squad_value=928.2,  squad_age=29.36, squad_caps=35.2, squad_cl=9),
    "Morocco":                 dict(fifa_rank=7,  gdp=148_000_000_000,   pop=37_712_505,  squad_value=447.7,  squad_age=26.60, squad_caps=26.8, squad_cl=6),   # GDP estimated
    "Scotland":                dict(fifa_rank=40, gdp=210_000_000_000,   pop=5_500_000,   squad_value=170.3,  squad_age=29.20, squad_caps=37.4, squad_cl=2),   # GDP & pop estimated
    "Haiti":                   dict(fifa_rank=100,gdp=25_224_154_991,    pop=11_637_398,  squad_value=55.9,   squad_age=27.51, squad_caps=24.0, squad_cl=0),

    # --- Group D ---
    "United States":           dict(fifa_rank=17, gdp=28_750_956_130_731,pop=336_806_231, squad_value=385.7,  squad_age=26.90, squad_caps=37.0, squad_cl=7),
    "Australia":               dict(fifa_rank=24, gdp=1_757_022_451_653, pop=26_000_000,  squad_value=77.5,   squad_age=27.36, squad_caps=28.2, squad_cl=0),
    "Paraguay":                dict(fifa_rank=52, gdp=44_458_118_397,    pop=6_844_146,   squad_value=153.7,  squad_age=29.00, squad_caps=26.5, squad_cl=0),
    "Turkey":                  dict(fifa_rank=23, gdp=1_359_123_768_774, pop=85_325_965,  squad_value=473.7,  squad_age=27.67, squad_caps=37.3, squad_cl=11),

    # --- Group E ---
    "Germany":                 dict(fifa_rank=10, gdp=4_685_592_577_805, pop=83_287_273,  squad_value=947.0,  squad_age=28.05, squad_caps=32.5, squad_cl=17),
    "Ecuador":                 dict(fifa_rank=28, gdp=124_676_074_700,   pop=17_980_083,  squad_value=368.7,  squad_age=26.08, squad_caps=29.7, squad_cl=5),
    "Ivory Coast":             dict(fifa_rank=42, gdp=87_113_179_149,    pop=31_165_654,  squad_value=522.1,  squad_age=25.85, squad_caps=27.0, squad_cl=6),
    "Curaçao":                 dict(fifa_rank=115,gdp=3_561_178_196,     pop=154_654,     squad_value=25.8,   squad_age=28.02, squad_caps=23.8, squad_cl=1),

    # --- Group F ---
    "Netherlands":             dict(fifa_rank=8,  gdp=1_214_927_698_573, pop=17_877_117,  squad_value=754.2,  squad_age=27.77, squad_caps=33.1, squad_cl=16),
    "Japan":                   dict(fifa_rank=18, gdp=4_027_597_523_551, pop=124_516_650, squad_value=270.9,  squad_age=27.50, squad_caps=30.6, squad_cl=5),
    "Sweden":                  dict(fifa_rank=32, gdp=603_715_224_266,   pop=10_536_632,  squad_value=406.1,  squad_age=27.56, squad_caps=20.0, squad_cl=9),
    "Tunisia":                 dict(fifa_rank=45, gdp=51_332_285_657,    pop=12_200_431,  squad_value=70.0,   squad_age=26.64, squad_caps=22.4, squad_cl=3),

    # --- Group G ---
    "Belgium":                 dict(fifa_rank=9,  gdp=630_000_000_000,   pop=11_779_946,  squad_value=547.5,  squad_age=27.61, squad_caps=41.7, squad_cl=12),  # GDP estimated
    "Iran":                    dict(fifa_rank=20, gdp=400_000_000_000,   pop=90_608_707,  squad_value=32.1,   squad_age=30.33, squad_caps=45.0, squad_cl=1),   # GDP estimated
    "Egypt":                   dict(fifa_rank=36, gdp=389_059_911_004,   pop=114_535_772, squad_value=116.5,  squad_age=29.06, squad_caps=31.6, squad_cl=2),
    "New Zealand":             dict(fifa_rank=95, gdp=260_172_385_098,   pop=5_200_000,   squad_value=34.3,   squad_age=28.27, squad_caps=31.7, squad_cl=0),

    # --- Group H ---
    "Spain":                   dict(fifa_rank=2,  gdp=1_725_671_652_742, pop=48_352_528,  squad_value=1220.0, squad_age=26.75, squad_caps=28.6, squad_cl=22),
    "Uruguay":                 dict(fifa_rank=16, gdp=77_000_000_000,    pop=3_388_081,   squad_value=359.3,  squad_age=28.74, squad_caps=35.9, squad_cl=6),   # GDP estimated
    "Saudi Arabia":            dict(fifa_rank=58, gdp=1_239_804_533_333, pop=33_702_731,  squad_value=40.7,   squad_age=28.52, squad_caps=35.7, squad_cl=0),
    "Cape Verde":              dict(fifa_rank=70, gdp=2_725_414_151,     pop=522_331,     squad_value=54.5,   squad_age=29.68, squad_caps=31.7, squad_cl=2),

    # --- Group I ---
    "France":                  dict(fifa_rank=3,  gdp=3_160_442_622_465, pop=68_372_286,  squad_value=1520.0, squad_age=27.00, squad_caps=30.9, squad_cl=16),
    "Senegal":                 dict(fifa_rank=15, gdp=31_000_000_000,    pop=18_077_573,  squad_value=478.1,  squad_age=27.09, squad_caps=37.9, squad_cl=9),   # GDP estimated
    "Iraq":                    dict(fifa_rank=60, gdp=279_641_257_615,   pop=45_074_049,  squad_value=21.2,   squad_age=26.91, squad_caps=31.8, squad_cl=0),
    "Norway":                  dict(fifa_rank=30, gdp=483_592_648_313,   pop=5_519_601,   squad_value=589.9,  squad_age=26.80, squad_caps=30.8, squad_cl=9),

    # --- Group J ---
    "Argentina":               dict(fifa_rank=1,  gdp=640_000_000_000,   pop=45_538_401,  squad_value=807.5,  squad_age=29.12, squad_caps=48.1, squad_cl=14),  # GDP estimated
    "Algeria":                 dict(fifa_rank=50, gdp=269_322_281_665,   pop=46_164_219,  squad_value=256.9,  squad_age=26.86, squad_caps=30.4, squad_cl=5),
    "Austria":                 dict(fifa_rank=26, gdp=534_790_720_467,   pop=9_131_761,   squad_value=245.2,  squad_age=28.61, squad_caps=38.6, squad_cl=6),
    "Jordan":                  dict(fifa_rank=78, gdp=53_352_289_577,    pop=11_439_213,  squad_value=20.3,   squad_age=28.47, squad_caps=40.9, squad_cl=0),

    # --- Group K ---
    "Portugal":                dict(fifa_rank=5,  gdp=290_000_000_000,   pop=10_578_174,  squad_value=1010.0, squad_age=28.04, squad_caps=44.6, squad_cl=15),  # GDP estimated
    "Colombia":                dict(fifa_rank=13, gdp=363_000_000_000,   pop=52_321_152,  squad_value=302.4,  squad_age=30.09, squad_caps=40.1, squad_cl=4),   # GDP estimated
    "Uzbekistan":              dict(fifa_rank=85, gdp=114_965_293_467,   pop=35_652_307,  squad_value=85.3,   squad_age=28.21, squad_caps=32.1, squad_cl=1),
    "DR Congo":                dict(fifa_rank=72, gdp=70_962_185_791,    pop=105_789_731, squad_value=143.9,  squad_age=29.07, squad_caps=30.6, squad_cl=1),

    # --- Group L ---
    "England":                 dict(fifa_rank=4,  gdp=3_686_033_044_482, pop=57_000_000,  squad_value=1360.0, squad_age=27.27, squad_caps=32.2, squad_cl=17),  # pop estimated
    "Croatia":                 dict(fifa_rank=11, gdp=82_000_000_000,    pop=3_859_686,   squad_value=387.3,  squad_age=28.33, squad_caps=44.6, squad_cl=8),   # GDP estimated
    "Ghana":                   dict(fifa_rank=65, gdp=82_308_110_386,    pop=33_787_914,  squad_value=234.4,  squad_age=26.98, squad_caps=21.6, squad_cl=5),
    "Panama":                  dict(fifa_rank=75, gdp=86_523_959_132,    pop=4_458_759,   squad_value=34.6,   squad_age=30.43, squad_caps=59.3, squad_cl=0),
}

# ── Pre-tournament outright winner odds (American moneyline) ──────────────────
# Source: BetMGM via Yahoo Sports, recorded before June 11 2026.
# https://sports.yahoo.com/soccer/betting/article/2026-world-cup-betting-odds-for-all-48-teams-to-win-the-title-145427136.html
# To convert to implied probability:
#   positive (+X): p = 100 / (100 + X)
# Note: raw implied probs sum > 1 (overround); normalise before use.

WC_2026_ODDS = {
    "France":                 450,
    "Spain":                  450,
    "England":                700,
    "Portugal":               700,
    "Argentina":              900,
    "Brazil":                 900,
    "Germany":               1400,
    "Netherlands":           1800,
    "Belgium":               3300,
    "Norway":                3300,
    "United States":         3300,
    "Colombia":              4000,
    "Morocco":               4000,
    "Mexico":                5000,
    "Japan":                 5000,
    "Switzerland":           6600,
    "Uruguay":               6600,
    "Croatia":               8000,
    "Senegal":               8000,
    "Sweden":                8000,
    "Australia":            10000,
    "Ecuador":              10000,
    "Ivory Coast":          10000,
    "Turkey":               12500,
    "Austria":              15000,
    "Canada":               15000,
    "Scotland":             15000,
    "South Korea":          20000,
    "Algeria":              25000,
    "Bosnia and Herzegovina":25000,
    "Egypt":                25000,
    "Czech Republic":       30000,
    "Paraguay":             30000,
    "Ghana":                50000,
    "Iran":                 50000,
    "DR Congo":             75000,
    "Tunisia":              75000,
    "Cape Verde":          100000,
    "Iraq":                100000,
    "Jordan":              100000,
    "New Zealand":         100000,
    "Panama":              100000,
    "Qatar":               100000,
    "Saudi Arabia":        100000,
    "South Africa":        100000,
    "Uzbekistan":          100000,
    "Curaçao":             250000,
    "Haiti":               250000,
}

def odds_to_prob_2026(team):
    """Convert WC_2026_ODDS entry to raw implied probability (not normalised)."""
    x = WC_2026_ODDS.get(team)
    if x is None:
        return None
    return 100 / (100 + x)  # all 2026 odds are positive (longshots)
