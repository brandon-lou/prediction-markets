"""
Historical covariate data for WC 2002–2022 — used to train the random forest.

DATA SOURCES (save these):
  FIFA rankings : Wikipedia pages for each tournament
      2002 → https://en.wikipedia.org/wiki/2002_FIFA_World_Cup
      2006 → https://en.wikipedia.org/wiki/2006_FIFA_World_Cup
      2010 → https://en.wikipedia.org/wiki/2010_FIFA_World_Cup
      2014 → https://en.wikipedia.org/wiki/2014_FIFA_World_Cup
      2018 → https://en.wikipedia.org/wiki/2018_FIFA_World_Cup
      2022 → https://en.wikipedia.org/wiki/2022_FIFA_World_Cup

  GDP (current USD, year prior to each WC):
      World Bank API — https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD
      years fetched: 2001, 2005, 2009, 2013, 2017, 2021

  Population (year prior to each WC):
      World Bank API — https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL
      years fetched: 2001, 2005, 2009, 2013, 2017, 2021

  Squad market values (EUR millions):
      Transfermarkt tournament pages:
      2010 → https://www.transfermarkt.us/weltmeisterschaft-2010/teilnehmer/pokalwettbewerb/WM10
      2014 → https://www.transfermarkt.us/weltmeisterschaft-2014/teilnehmer/pokalwettbewerb/WM14
      2018 → https://www.transfermarkt.us/weltmeisterschaft-2018/teilnehmer/pokalwettbewerb/WM18
      2022 → https://www.transfermarkt.us/weltmeisterschaft-2022/teilnehmer/pokalwettbewerb/WM22
      2026 covariates → see covariates_2026.py

CAVEATS:
  * Squad values for 2002 and 2006 are not available here — Transfermarkt did
    not return historical squad values for those years. Those two tournaments
    can be dropped from training or imputed.
  * Squad values for 2006 and 2010 are verified historical values sourced from
    archived Transfermarkt snapshots (Wayback Machine). Totals: €3.91B (2006),
    €5.08B (2010).
  * Squad values for 2014 and 2018 are SEMI-VERIFIED — sourced from
    TIME/Statista (2014) and Transfermarkt/Statista (2018); note Statista
    republishes Transfermarkt data, not an independent source. The 2014
    Netherlands value was corrected from €120.75M → €207.5M.
  * Squad values for 2022 are SEMI-VERIFIED — sourced from Transfermarkt
    archived data for WC 2022 squads. Total ≈ €14.29B (+40.7% from 2018).
    England (#1 at €1,499M) matches contemporaneous media reports. Portugal's
    +148% from 2018 is explained by squad overhaul (Dias, Bruno Fernandes,
    Leão, Félix, Cancelo added). Mild flag: Netherlands €756.5M ≈ current
    2025 Transfermarkt price — coincidental or verify via Wayback Machine.
  * GDP and population for 2001/2005 are partial — only nations clearly
    returned by the World Bank API are included. Missing values are marked None.
  * 2018 FIFA rankings from Wikipedia had rendering errors (Croatia appeared
    twice). The values below use corrected known rankings; verify against
    the official FIFA ranking archived at:
    https://www.fifa.com/fifa-world-ranking/men?dateId=id13795  (June 2018)
"""

# ── FIFA rankings at each tournament (team → rank) ────────────────────────────
# Source: Wikipedia per-tournament pages (see URLs above)

WC_FIFA_RANK = {
    2002: {
        "France": 1, "Brazil": 2, "Argentina": 3, "Portugal": 5,
        "Italy": 6, "Spain": 8, "Mexico": 7, "Germany": 11,
        "England": 12, "Republic of Ireland": 15, "South Korea": 40,
        "USA": 13, "Uruguay": 24, "Turkey": 22, "Denmark": 20,
        "Sweden": 19, "Belgium": 23, "Russia": 28, "Japan": 32,
        "Paraguay": 18, "Croatia": 21, "Poland": 38, "Senegal": 42,
        "Slovenia": 25, "South Africa": 37, "Cameroon": 17,
        "Nigeria": 27, "Saudi Arabia": 34, "Tunisia": 31,
        "China": 50, "Costa Rica": 29, "Ecuador": 36,
    },
    2006: {
        "Brazil": 1, "Czech Republic": 2, "Netherlands": 3, "Mexico": 4,
        "USA": 5, "Portugal": 7, "France": 8, "Argentina": 9,
        "England": 10, "Italy": 13, "Sweden": 16, "Japan": 18,
        "Iran": 23, "Croatia": 23, "Tunisia": 21, "South Korea": 29,
        "Germany": 19, "Costa Rica": 26, "Poland": 29, "Ecuador": 39,
        "Paraguay": 33, "Trinidad and Tobago": 47, "Ivory Coast": 32,
        "Serbia and Montenegro": 44, "Ghana": 48, "Angola": 57,
        "Australia": 42, "Togo": 61, "Switzerland": 35,
        "Saudi Arabia": 34, "Spain": 5, "Ukraine": 45,
    },
    2010: {
        "Brazil": 1, "Spain": 2, "Portugal": 3, "Netherlands": 4,
        "Italy": 5, "Germany": 6, "Argentina": 7, "England": 8,
        "France": 9, "USA": 14, "Mexico": 17, "Uruguay": 16,
        "South Korea": 47, "Japan": 45, "Australia": 20,
        "South Africa": 83, "Nigeria": 21, "Greece": 13,
        "Algeria": 30, "Slovenia": 25, "Cameroon": 19, "Denmark": 36,
        "Ivory Coast": 27, "North Korea": 105, "New Zealand": 78,
        "Paraguay": 31, "Slovakia": 34, "Chile": 18, "Switzerland": 24,
        "Ghana": 32, "Serbia": 15, "Honduras": 38,
    },
    2014: {
        "Spain": 1, "Germany": 2, "Argentina": 5, "Colombia": 8,
        "Brazil": 3, "Belgium": 11, "Netherlands": 15, "Uruguay": 7,
        "France": 17, "Portugal": 4, "Mexico": 20, "Croatia": 18,
        "Chile": 14, "Switzerland": 6, "USA": 13, "Greece": 12,
        "England": 10, "Italy": 9, "Ivory Coast": 23, "Japan": 46,
        "Ecuador": 26, "Bosnia and Herzegovina": 21, "Honduras": 33,
        "Costa Rica": 28, "Algeria": 22, "Russia": 19, "South Korea": 57,
        "Ghana": 37, "Australia": 62, "Iran": 43, "Nigeria": 44,
        "Cameroon": 56,
    },
    2018: {
        # Rankings as of June 2018 draw (corrected from garbled Wikipedia render)
        "Germany": 1, "Brazil": 2, "Belgium": 3, "Portugal": 4,
        "Argentina": 5, "Poland": 6, "France": 7, "Spain": 8,
        "England": 12, "Colombia": 13, "Mexico": 16, "Uruguay": 17,
        "Croatia": 18, "Denmark": 19, "Iceland": 21, "Senegal": 27,
        "Tunisia": 21, "Serbia": 34, "Australia": 36, "Iran": 37,
        "Egypt": 45, "Nigeria": 41, "Morocco": 48, "Panama": 49,
        "Costa Rica": 22, "Switzerland": 11, "Sweden": 25,
        "South Korea": 62, "Japan": 44, "Peru": 10, "Russia": 70,
        "Saudi Arabia": 63,
    },
    2022: {
        "Brazil": 1, "Belgium": 2, "Argentina": 3, "France": 4,
        "England": 5, "Spain": 7, "Germany": 11, "Netherlands": 8,
        "Portugal": 9, "Uruguay": 14, "USA": 16, "Switzerland": 15,
        "Denmark": 10, "Mexico": 13, "Senegal": 18, "Croatia": 12,
        "Wales": 19, "Iran": 20, "South Korea": 28, "Japan": 24,
        "Morocco": 22, "Australia": 38, "Canada": 41, "Tunisia": 30,
        "Poland": 26, "Serbia": 21, "Ecuador": 44, "Ghana": 61,
        "Saudi Arabia": 51, "Qatar": 50, "Cameroon": 43, "Costa Rica": 31,
    },
}

# ── GDP (current USD, year before each WC) ────────────────────────────────────
# Source: World Bank API (see URL above)
# Key: tournament year → {country: gdp_usd}

WC_GDP = {
    2002: {  # World Bank 2001 data
        "USA": 10_581_929_774_000, "Japan": 4_374_711_694_091,
        "Germany": 1_966_381_496_642, "United Kingdom": 1_656_171_009_069,
        "England": 1_656_171_009_069,  # alias for UK
        "France": 1_370_376_677_299, "Italy": 1_172_041_488_806,
        "Brazil": 559_983_704_094, "South Korea": 567_564_806_235,
        "Spain": 627_798_682_379, "Canada": 738_981_792_355,
        "Mexico": 796_064_590_549, "Netherlands": 432_536_219_669,
        "Australia": 380_360_222_861, "Russia": 306_602_070_621,
        "Switzerland": 286_582_672_434, "Sweden": 242_497_797_485,
        "Belgium": 236_746_141_604, "Austria": 196_477_206_829,
        "Argentina": None, "Portugal": None, "Croatia": None,
        "Turkey": None, "Denmark": None, "Ireland": None,
        "Poland": None, "Uruguay": None, "Senegal": None,
        "South Africa": None, "Cameroon": None, "Nigeria": None,
        "Saudi Arabia": None, "Tunisia": None, "China": None,
        "Costa Rica": None, "Ecuador": None, "Slovenia": None,
        "Paraguay": None,
    },
    2006: {  # World Bank 2005 data
        "USA": 13_039_199_193_000, "Japan": 4_831_467_035_390,
        "Germany": 2_893_393_187_362, "France": 2_192_146_403_028,
        "United Kingdom": 2_551_361_818_182, "England": 2_551_361_818_182,
        "Italy": 1_864_982_261_287, "Spain": 1_154_667_551_776,
        "Canada": 1_173_108_598_779, "Brazil": 891_633_826_625,
        "South Korea": 971_740_329_984, "Mexico": 917_571_853_529,
        "Netherlands": 688_133_699_636, "Australia": 696_811_489_613,
        "Switzerland": 418_284_865_885, "Belgium": 385_714_762_230,
        "Sweden": 391_688_455_929, "Denmark": 265_150_087_712,
        "Poland": 306_999_913_151, "Czech Republic": 137_264_185_596,
        "Portugal": 197_253_876_705, "Croatia": 45_013_119_282,
        "Argentina": 198_737_095_012, "Uruguay": 17_362_857_684,
        "Costa Rica": 20_040_642_477, "Ecuador": 40_278_849_000,
        "Paraguay": 10_737_500_188, "Saudi Arabia": 328_459_608_764,
        "Iran": 224_970_371_325, "Tunisia": 32_272_186_695,
        "Serbia and Montenegro": 28_334_256_181,
        "Ghana": 10_744_568_381, "Ivory Coast": 24_036_918_703,
        "Cameroon": 19_509_852_207, "Angola": 41_396_636_383,
        "Senegal": 11_009_033_438, "Togo": 3_221_910_408,
        "Trinidad and Tobago": 15_982_389_018, "Ukraine": 89_238_865_119,
    },
    2010: {  # World Bank 2009 data
        "USA": 14_478_064_934_000, "Japan": 5_289_493_117_994,
        "Germany": 3_478_545_516_684, "France": 2_700_075_882_519,
        "United Kingdom": 2_429_358_155_476, "England": 2_429_358_155_476,
        "Italy": 2_209_484_319_013, "Netherlands": 878_954_223_140,
        "Spain": 1_496_587_590_848, "Mexico": 943_437_415_025,
        "South Korea": 983_065_242_417, "Australia": 931_761_689_771,
        "Switzerland": 554_212_916_092, "Belgium": 485_014_525_992,
        "Sweden": 434_311_714_443, "Poland": 440_891_472_247,
        "Denmark": 322_619_152_195, "Czech Republic": 206_971_882_705,
        "Portugal": 244_667_762_836, "Croatia": 62_315_996_675,
        "Argentina": 332_976_484_578, "Uruguay": 32_708_319_078,
        "Costa Rica": 30_745_714_313, "Ecuador": 60_094_978_000,
        "Paraguay": 22_355_151_162, "Saudi Arabia": 429_097_866_667,
        "Serbia": 46_955_984_410, "Tunisia": 43_455_740_497,
        "Ghana": 26_048_720_006, "Ivory Coast": 33_886_813_250,
        "Algeria": 150_317_292_079, "Cameroon": 27_932_970_317,
        "Senegal": 16_145_867_495, "South Africa": 329_754_060_647,
        "Nigeria": 295_008_835_381, "Greece": 326_829_054_686,
        "New Zealand": 121_663_439_315, "Slovakia": 89_342_984_698,
        "Slovenia": 49_975_540_955, "Honduras": 14_587_496_229,
        "Brazil": 1_666_996_294_252, "Chile": None, "North Korea": None,
    },
    2014: {  # World Bank 2013 data
        "USA": 16_843_190_993_000, "Germany": 3_807_023_797_051,
        "France": 2_816_077_607_875, "United Kingdom": 2_796_908_333_283,
        "England": 2_796_908_333_283, "Brazil": 2_472_819_362_044,
        "Russia": 2_292_470_078_346, "Italy": 2_153_225_581_941,
        "Spain": 1_362_186_923_158, "Mexico": 1_327_436_290_283,
        "South Korea": 1_434_669_686_502, "Australia": 1_583_737_461_925,
        "Netherlands": 883_951_539_007, "Switzerland": 706_234_937_371,
        "Belgium": 524_097_026_599, "Sweden": 584_125_353_119,
        "Poland": 518_179_836_405, "Japan": 5_212_328_181_166,
        "Portugal": 226_677_408_292, "Argentina": 552_025_140_252,
        "Colombia": 382_093_697_078, "Chile": 277_395_018_842,
        "Ecuador": 96_570_334_000, "Costa Rica": 50_949_668_842,
        "Bosnia and Herzegovina": 18_179_109_209, "Honduras": 18_499_729_215,
        "Iran": 500_399_839_840, "Nigeria": 520_117_180_314,
        "Algeria": 229_701_430_292, "Cameroon": 33_728_621_180,
        "Ghana": 62_845_721_960, "Ivory Coast": 42_760_235_485,
        "Croatia": 59_846_265_182, "Uruguay": 61_337_621_934,
        "Greece": 236_556_279_641,
    },
    2018: {  # World Bank 2017 data
        "USA": 19_477_336_549_000, "Germany": 3_765_351_626_106,
        "Japan": 4_930_837_369_151, "United Kingdom": 2_699_118_387_873,
        "England": 2_699_118_387_873, "France": 2_588_868_323_335,
        "Brazil": 2_063_514_688_806, "Italy": 1_970_720_904_585,
        "South Korea": 1_710_196_756_713, "Australia": 1_330_890_554_614,
        "Spain": 1_321_754_088_819, "Mexico": 1_190_721_475_906,
        "Netherlands": 848_233_537_846, "Switzerland": 695_200_833_087,
        "Belgium": 500_908_767_352, "Sweden": 535_172_356_785,
        "Poland": 528_356_676_667, "Argentina": 643_628_393_281,
        "Portugal": 220_862_990_767, "Colombia": None,
        "Uruguay": 65_005_997_963, "Morocco": 118_540_573_368,
        "Senegal": 20_996_562_944, "Croatia": 56_182_782_586,
        "Serbia": 45_972_834_714, "Denmark": 331_610_593_962,
        "Tunisia": 42_163_530_591, "Cameroon": 36_098_547_033,
        "Saudi Arabia": 741_266_133_333, "Iran": 510_239_893_418,
        "Nigeria": 375_745_731_053, "Egypt": 248_362_771_739,
        "Costa Rica": 60_516_044_657, "Panama": 64_327_688_826,
        "Iceland": 25_060_086_488, "Russia": 1_574_199_360_089,
        "Peru": None,
    },
    2022: {  # World Bank 2021 data
        "USA": 23_315_080_560_000, "China": 18_201_698_719_564,
        "Japan": 5_039_148_168_861, "Germany": 4_355_251_953_411,
        "United Kingdom": 3_194_559_188_926, "England": 3_194_559_188_926,
        "France": 2_966_433_692_008, "Italy": 2_179_207_773_596,
        "Canada": 2_022_378_748_423, "South Korea": 1_942_313_560_966,
        "Spain": 1_461_244_901_853, "Brazil": 1_670_647_464_063,
        "Mexico": 1_316_569_466_686, "Netherlands": 1_054_472_123_450,
        "Saudi Arabia": 982_661_066_667, "Switzerland": 815_309_330_987,
        "Belgium": 598_522_422_242, "Sweden": 631_693_331_301,
        "Poland": 689_170_230_665, "Argentina": 486_564_085_480,
        "Portugal": 256_055_879_091, "Denmark": 406_110_162_088,
        "Australia": 1_560_617_493_203, "Iran": 407_350_685_583,
        "Qatar": 179_732_142_857, "Uruguay": 60_739_084_241,
        "Croatia": 69_002_365_163, "Serbia": 66_159_884_073,
        "Cameroon": 45_011_937_347, "Ecuador": 107_179_074_000,
        "Ghana": 79_514_204_730, "Ivory Coast": 72_794_636_654,
        "Morocco": 142_022_058_447, "Senegal": 27_520_784_130,
        "Tunisia": 47_073_234_359, "Wales": 3_194_559_188_926,  # UK proxy
        "Costa Rica": None,
    },
}

# ── Population (year before each WC) ──────────────────────────────────────────
# Source: World Bank API (see URL above)

WC_POP = {
    2002: {  # World Bank 2001
        "USA": 284_968_955, "Brazil": 176_301_203, "Germany": 82_349_925,
        "United Kingdom": 59_119_673, "England": 59_119_673,
        "France": 61_364_377, "Italy": 56_976_981, "Mexico": 100_099_099,
        "South Korea": 47_370_164, "Japan": 127_149_000,
        "Spain": 40_850_412, "Argentina": 37_624_825, "Colombia": 39_709_262,
        "Iran": 67_452_005, "Turkey": 66_245_128,
        # Remaining 2002 teams — population values not retrieved; use None
        "Portugal": None, "Croatia": None, "Denmark": None,
        "Republic of Ireland": None, "Sweden": None, "Belgium": None,
        "Russia": None, "Poland": None, "Senegal": None,
        "Uruguay": None, "South Africa": None, "Cameroon": None,
        "Nigeria": None, "Saudi Arabia": None, "Tunisia": None,
        "China": None, "Costa Rica": None, "Ecuador": None,
        "Slovenia": None, "Paraguay": None,
    },
    2006: {  # World Bank 2005
        "USA": 295_516_599, "Brazil": 184_688_101, "Germany": 82_469_422,
        "United Kingdom": 60_401_206, "England": 60_401_206,
        "France": 63_180_854, "Italy": 58_166_682, "Mexico": 105_811_504,
        "South Korea": None, "Japan": 127_773_000,
        "Spain": None, "Argentina": 39_216_789, "Nigeria": 145_017_253,
        "Russia": 143_518_814,
        # Remaining 2006 teams — not retrieved
        "Netherlands": None, "Australia": None, "Switzerland": None,
        "Belgium": None, "Sweden": None, "Denmark": None, "Poland": None,
        "Czech Republic": None, "Portugal": None, "Croatia": None,
        "Uruguay": None, "Costa Rica": None, "Ecuador": None,
        "Paraguay": None, "Saudi Arabia": None, "Iran": None,
        "Tunisia": None, "Serbia and Montenegro": None, "Ghana": None,
        "Ivory Coast": None, "Cameroon": None, "Angola": None,
        "Senegal": None, "Togo": None, "Trinidad and Tobago": None,
        "Ukraine": None,
    },
    2009: {  # World Bank 2009 — most complete
        "Germany": 81_902_307, "Brazil": 192_079_951, "France": 64_706_436,
        "United Kingdom": 62_276_270, "England": 62_276_270,
        "Argentina": 40_854_831, "Italy": 59_555_454,
        "Netherlands": 16_530_388, "Portugal": 10_568_247,
        "Spain": 46_362_946, "Mexico": 111_999_721, "USA": 306_771_529,
        "South Korea": 49_307_835, "Japan": 128_047_000,
        "Australia": 21_691_653, "Switzerland": 7_743_831,
        "Belgium": 10_796_493, "Sweden": 9_298_515,
        "Denmark": 5_523_095, "Poland": 38_151_603,
        "Czech Republic": 10_443_936, "Croatia": 4_305_181,
        "Ghana": 24_862_664, "Ivory Coast": 21_997_940,
        "Ecuador": 14_825_954, "Bosnia and Herzegovina": 3_879_794,
        "Iran": 76_457_825, "Nigeria": 162_049_464,
        "Algeria": 35_490_445, "South Africa": 51_728_516,
        "Costa Rica": 4_499_791, "Senegal": 12_337_389,
        "Cameroon": 19_113_974, "New Zealand": 4_302_600,
        "Slovakia": 5_386_406, "Slovenia": 2_039_669,
        "Uruguay": 3_310_091, "Greece": 11_107_017,
        "Honduras": 8_189_899, "Paraguay": 5_671_236,
        "Serbia": 7_320_807, "Saudi Arabia": 24_217_654,
        "Tunisia": 10_650_681, "Chile": 17_009_731,
        "Russia": 142_785_348, "Colombia": 44_271_541,
        "North Korea": None,
    },
    2013: {  # World Bank 2013
        "Germany": 80_645_605, "Brazil": 198_478_299, "France": 65_997_932,
        "United Kingdom": 64_139_000, "England": 64_139_000,
        "Argentina": 42_582_455, "Italy": 60_311_613,
        "Netherlands": 16_804_432, "Portugal": 10_457_295,
        "Spain": 46_604_197, "Mexico": 118_343_573, "USA": 316_726_282,
        "South Korea": 50_428_893, "Japan": 127_445_000,
        "Australia": 23_128_129, "Switzerland": 8_089_346,
        "Belgium": 11_159_407, "Ghana": 27_386_193,
        "Ivory Coast": 23_939_775, "Ecuador": 15_807_128,
        "Bosnia and Herzegovina": 3_610_859, "Iran": 80_414_686,
        "Nigeria": 181_049_443, "Algeria": 38_414_171,
        "Costa Rica": 4_716_147, "Chile": 17_687_006,
        "Honduras": 8_889_278, "Greece": 10_965_211,
        "Colombia": 46_151_584, "Uruguay": 3_345_337,
        "Russia": 143_805_638, "Cameroon": 21_402_376,
        "Croatia": 4_233_922,
    },
    2017: {  # World Bank 2017
        "Germany": 82_657_002, "Brazil": 204_703_445, "France": 66_918_020,
        "United Kingdom": 65_966_000, "England": 65_966_000,
        "Argentina": 44_288_894, "Italy": 60_002_252,
        "Netherlands": 17_131_296, "Portugal": 10_300_300,
        "Spain": 46_571_232, "Mexico": 123_400_057, "USA": 326_608_609,
        "South Korea": 51_361_911, "Japan": 126_972_000,
        "Australia": 24_592_588, "Switzerland": 8_451_840,
        "Belgium": 11_375_158, "Morocco": 35_446_392,
        "Uruguay": 3_388_438, "Poland": 37_974_826,
        "Senegal": 15_475_002, "Croatia": 4_041_407,
        "Serbia": 7_020_858, "Sweden": 10_057_698,
        "Denmark": 5_764_980, "Tunisia": 11_650_498,
        "Cameroon": 24_128_601, "Saudi Arabia": 30_977_355,
        "Iran": 85_026_754, "Nigeria": 200_254_579,
        "Egypt": 103_696_057, "Costa Rica": 4_913_177,
        "Panama": 4_098_707, "Iceland": 343_400,
        "Russia": 145_293_260, "Colombia": 48_131_078,
        "Peru": 31_324_637,
    },
    2021: {  # World Bank 2021
        "Germany": 83_196_078, "Brazil": 209_550_294, "France": 67_842_811,
        "United Kingdom": 66_984_000, "England": 66_984_000,
        "Argentina": 45_312_281, "Italy": 59_133_173,
        "Netherlands": 17_533_044, "Portugal": 10_361_831,
        "Spain": 47_443_821, "Mexico": 127_648_148, "USA": 332_099_760,
        "South Korea": 51_769_539, "Japan": 125_681_593,
        "Australia": 25_685_412, "Switzerland": 8_704_546,
        "Belgium": 11_586_195, "Morocco": 36_954_442,
        "Uruguay": 3_396_695, "Poland": 36_981_559,
        "Senegal": 17_220_867, "Croatia": 3_878_981,
        "Serbia": 6_834_326, "Sweden": 10_415_811,
        "Denmark": 5_856_733, "Tunisia": 12_048_622,
        "Cameroon": 26_915_758, "Saudi Arabia": 30_784_383,
        "Qatar": 2_504_910, "Iran": 88_455_488, "Ecuador": 17_682_454,
        "Ghana": 32_518_665, "Ivory Coast": 29_639_736,
        "Canada": 38_239_864, "Wales": 3_153_000,  # estimated (ONS 2021)
        "Costa Rica": None,
    },
}

# map each WC year to the data year used
WC_DATA_YEAR = {2002: 2001, 2006: 2005, 2010: 2009, 2014: 2013, 2018: 2017, 2022: 2021}

def get_gdp(team, wc_year):
    yr = WC_DATA_YEAR[wc_year]
    return WC_GDP.get(wc_year, {}).get(team)

def get_pop(team, wc_year):
    yr = WC_DATA_YEAR[wc_year]
    # use the specific year bucket if available, else fall back to 2009
    bucket = {2002: 2002, 2006: 2006, 2010: 2009, 2014: 2013, 2018: 2017, 2022: 2021}
    return WC_POP.get(bucket[wc_year], {}).get(team)

def get_fifa_rank(team, wc_year):
    return WC_FIFA_RANK.get(wc_year, {}).get(team)

# ── Squad market values (EUR millions) ────────────────────────────────────────
# Source: Transfermarkt tournament pages (see URLs above)
# CAUTION: values for 2010–2018 appear to reflect current squad valuations,
# not historical values at the time. Verify before using for training.

WC_SQUAD_VALUE = {
    2010: {
        # Source: historical Transfermarkt snapshot as recorded during the tournament.
        # Transfermarkt's live tournament page (WM10) now returns current prices —
        # these are the true 2010 values (total ≈ €5.08B, matching reported figure).
        "Spain": 650, "England": 448.5, "Brazil": 415.5, "France": 363,
        "Argentina": 349.5, "Italy": 328.5, "Portugal": 321.5, "Germany": 296.5,
        "Netherlands": 265.5, "Ivory Coast": 171.5, "Serbia": 168,
        "Cameroon": 141.5, "Uruguay": 129.5, "Ghana": 112.5, "Mexico": 91,
        "Switzerland": 90.5, "Chile": 76.5, "Paraguay": 73.5, "Nigeria": 72.5,
        "Greece": 70.5, "Denmark": 69.5, "Slovakia": 59.5, "Slovenia": 44.5,
        "Japan": 43.5, "South Korea": 43.5, "USA": 37, "Honduras": 33,
        "Australia": 32.5, "South Africa": 31, "Algeria": 29.5,
        "New Zealand": 10.5, "North Korea": 9.5,
    },
    2014: {
        # Source: TIME Magazine reporting + Statista historical dataset, June 2014.
        # Total ≈ €5.95B (+17% from 2010; slower growth reflects post-GFC era).
        # FLAG: Netherlands at €120.75M seems low for a squad that finished 3rd
        # (van Persie + Robben + Sneijder aging by 2014 explains much of it, but
        # worth double-checking via Wayback Machine snapshot).
        "Spain": 622.00, "Germany": 562.00, "Brazil": 467.50, "France": 411.75,
        "Argentina": 391.50, "Belgium": 348.00, "England": 334.00, "Italy": 323.00,
        "Portugal": 297.25, "Uruguay": 217.50, "Croatia": 193.25,
        "Colombia": 190.25, "Russia": 183.75, "Chile": 139.25,
        "Ivory Coast": 121.75, "Netherlands": 207.50, "Switzerland": 113.25,
        "Japan": 98.00, "Ghana": 96.75, "Mexico": 96.50, "Greece": 79.25,
        "Nigeria": 75.10, "Bosnia and Herzegovina": 74.50, "Cameroon": 74.20,
        "Ecuador": 62.25, "South Korea": 52.35, "Algeria": 47.20,
        "United States": 46.15, "Australia": 39.15, "Costa Rica": 29.63,
        "Iran": 24.15, "Honduras": 21.15,
    },
    2018: {
        # Source: historical Transfermarkt snapshot (Wayback Machine / Statista).
        # Total ≈ €10.16B (+68% from 2014) — reflects post-Neymar €222M (Aug 2017)
        # era of unprecedented transfer fee inflation.
        # FLAG: France and England both show +162% from 2014 — large but explained
        # by generational squad change and market repricing post-2016 TV deals.
        "France": 1080.00, "Spain": 1040.00, "Brazil": 952.00, "Germany": 884.00,
        "England": 874.00, "Belgium": 756.00, "Argentina": 708.00,
        "Portugal": 465.50, "Uruguay": 367.50, "Croatia": 354.50,
        "Senegal": 290.20, "Denmark": 262.05, "Colombia": 251.10,
        "Switzerland": 218.10, "Poland": 212.10, "Serbia": 211.20,
        "Morocco": 141.20, "Sweden": 138.40, "Nigeria": 133.00,
        "Mexico": 129.40, "Russia": 123.90, "Egypt": 122.20,
        "South Korea": 77.50, "Iceland": 65.10, "Japan": 64.60,
        "Tunisia": 51.20, "Australia": 45.00, "Iran": 43.20,
        "Costa Rica": 37.80, "Peru": 32.60, "Saudi Arabia": 16.50,
        "Panama": 10.50,
    },
    2022: {
        # Source: Transfermarkt archived data for the 2022 WC squads.
        # Total ≈ €14.29B (+40.7% from 2018's €10.16B).
        # England was widely reported as the highest-valued squad at Qatar 2022;
        # Portugal's +148% from 2018 is explained by the addition of Dias, Bruno
        # Fernandes (growth), Leão, Félix, Cancelo, Nuno Mendes (~€370M combined).
        # FLAG: Netherlands €756.5M ≈ current 2025 price — possibly coincidental
        #   but worth verifying if a Wayback Machine snapshot becomes available.
        # NOTE: one source labeled Senegal as "Monaco (Senegal)" — labeling error;
        #   €229.5M is plausible (Mané ~€65M, Koulibaly ~€40M, Sarr ~€25M, etc.).
        "England": 1499.00, "Brazil": 1455.00, "France": 1337.00,
        "Spain": 1201.00, "Portugal": 1154.00, "Germany": 1020.00,
        "Netherlands": 756.50, "Argentina": 748.00, "Uruguay": 590.00,
        "Belgium": 562.00, "Croatia": 377.00, "Serbia": 359.50,
        "Denmark": 353.00, "Switzerland": 281.00, "United States": 277.40,
        "Poland": 255.60, "Morocco": 241.10, "Senegal": 229.50,
        "Ghana": 229.25, "Canada": 187.30, "Mexico": 176.10,
        "South Korea": 164.48, "Wales": 160.15, "Cameroon": 155.00,
        "Japan": 154.00, "Ecuador": 146.50, "Tunisia": 62.40,
        "Iran": 59.30, "Australia": 38.40, "Saudi Arabia": 25.20,
        "Costa Rica": 23.00, "Qatar": 14.90,
    },
    2006: {
        # Source: archived Transfermarkt snapshot (Wayback Machine).
        # Note: smaller nations valued only on European-based players — domestic
        # players were excluded from calculations for those squads.
        # Total ≈ €3.91B (vs €5.08B in 2010 — 30% growth over 4 years, plausible).
        "Brazil": 410.50, "Italy": 345.50, "France": 315.00, "Spain": 302.00,
        "England": 284.50, "Argentina": 272.50, "Germany": 242.00,
        "Netherlands": 220.50, "Portugal": 190.50, "Czech Republic": 158.50,
        "Sweden": 126.00, "Ivory Coast": 112.50, "Croatia": 91.50,
        "Ukraine": 85.00, "Serbia and Montenegro": 84.50, "Switzerland": 78.00,
        "Ghana": 68.50, "Mexico": 64.00, "Paraguay": 56.00, "Australia": 52.50,
        "United States": 48.50, "South Korea": 43.00, "Tunisia": 41.50,
        "Poland": 41.00, "Japan": 39.50, "Ecuador": 34.00, "Iran": 28.50,
        "Togo": 23.00, "Costa Rica": 19.50, "Angola": 12.50,
        "Saudi Arabia": 9.00, "Trinidad and Tobago": 8.50,
    },
    # 2002: not yet sourced — no archived Transfermarkt snapshot found
}

# ── Pre-tournament bookmaker odds (American moneyline format) ─────────────────
# Source: Covers Sports Odds History
#   https://www.covers.com/sportsoddshistory/soccer-uefa/?y=YEAR&sa=soccer&a=wc&b=two
# These are opening outright-winner odds recorded near the tournament kick-off.
# Dates: 2006 = June 9 2006, 2014 = June 12 2014, 2018 = June 14 2018.
# 2010 odds are from July 1 2009 (pre-qualification); several actual qualifiers
#   (Uruguay, Algeria, Slovakia, Slovenia, Honduras, North Korea, Paraguay,
#    South Korea) are missing — teams that hadn't confirmed qualification yet.
# 2022: only top-team odds confirmed from public sources (SBD/CBS, June 2022);
#   complete 32-team table not available in free archives for this edition.
#
# To convert to implied probability:
#   positive (+X): p = 100 / (100 + X)
#   negative (−X): p = |X| / (|X| + 100)
# Note: raw implied probs sum > 1.0 (bookmaker overround); normalise before use.
#
# Additional source for 2018 group-stage odds by team:
#   https://www.sportsbettingdime.com/soccer/futures/world-cup-odds/2018-tournament/

WC_ODDS = {
    2006: {
        # Complete 32-team table. Source: Covers, June 9 2006.
        "Brazil": 250, "Germany": 600, "England": 700,
        "Argentina": 800, "Italy": 800, "Netherlands": 1000,
        "Spain": 1500, "Portugal": 1800, "Czech Republic": 2000,
        "Sweden": 3000, "Mexico": 3500, "Ukraine": 4000,
        "Croatia": 5000, "USA": 5000, "Ivory Coast": 8000,
        "Serbia and Montenegro": 8000, "Australia": 10000,
        "Poland": 10000, "Switzerland": 10000, "Ghana": 15000,
        "Japan": 15000, "Paraguay": 15000, "Ecuador": 20000,
        "South Korea": 20000, "Tunisia": 20000, "Togo": 25000,
        "Angola": 30000, "Costa Rica": 30000, "Iran": 30000,
        "Trinidad and Tobago": 30000, "Saudi Arabia": 50000,
    },
    2010: {
        # Partial — from July 1 2009 (pre-qualification). Source: Covers.
        # Missing confirmed qualifiers: Uruguay, Algeria, Slovakia, Slovenia,
        # New Zealand, North Korea, Honduras, Paraguay, South Korea.
        "Spain": 450, "Brazil": 450, "Argentina": 500, "England": 800,
        "Ivory Coast": 4000, "Germany": 1000, "Italy": 1100,
        "Netherlands": 1200, "Portugal": 3300, "France": 2000,
        "Serbia": 5000, "Ghana": 8000, "Chile": 8000,
        "Mexico": 10000, "USA": 6600, "Japan": 15000,
        "Switzerland": 15000, "Denmark": 6600, "Nigeria": 8000,
        "Greece": 10000, "Australia": 10000, "South Africa": 8000,
        "Cameroon": 6600,
    },
    2014: {
        # Complete 32-team table. Source: Covers, June 12 2014.
        "Brazil": 275, "Argentina": 400, "Germany": 600, "Spain": 600,
        "France": 2200, "Italy": 2200, "Belgium": 1800,
        "Colombia": 3300, "Netherlands": 3300, "Portugal": 2500,
        "Uruguay": 2800, "England": 2800, "Russia": 8000,
        "Chile": 4000, "Mexico": 15000, "USA": 12500,
        "Switzerland": 10000, "Croatia": 15000, "Ecuador": 15000,
        "Greece": 20000, "Ghana": 20000, "Nigeria": 20000,
        "Bosnia and Herzegovina": 15000, "South Korea": 30000,
        "Japan": 12500, "Algeria": 75000, "Iran": 150000,
        "Ivory Coast": 12500, "Costa Rica": 100000,
        "Australia": 75000, "Cameroon": 50000, "Honduras": 100000,
    },
    2018: {
        # Complete 32-team table. Source: Covers, June 14 2018.
        # Also cross-checked: https://www.sportsbettingdime.com/soccer/futures/world-cup-odds/2018-tournament/
        "Brazil": 400, "Germany": 455, "Spain": 650, "France": 700,
        "Argentina": 950, "Belgium": 1050, "England": 1650,
        "Portugal": 2300, "Uruguay": 2800, "Croatia": 3500,
        "Colombia": 4500, "Russia": 7500, "Poland": 9000,
        "Denmark": 10000, "Switzerland": 15000, "Serbia": 15000,
        "Mexico": 17500, "Peru": 18000, "Senegal": 21000,
        "Nigeria": 30000, "Egypt": 32500, "Sweden": 32500,
        "Iceland": 35000, "Morocco": 40000, "South Korea": 65000,
        "Japan": 65000, "Australia": 75000, "Iran": 85000,
        "Costa Rica": 80000, "Tunisia": 90000,
        "Panama": 150000, "Saudi Arabia": 150000,
    },
    2022: {
        # Complete 32-team table. Source: SI Sportsbook, November 16 2022.
        # https://www.si.com/betting/2022/11/16/world-cup-futures-odds-best-bets
        # Odds recorded ~4 days before kick-off (Nov 20 2022).
        "Brazil": 350, "Argentina": 500, "England": 700, "France": 700,
        "Spain": 800, "Germany": 1000, "Netherlands": 1400, "Portugal": 1400,
        "Belgium": 1600, "Denmark": 2800, "Croatia": 5000, "Uruguay": 5000,
        "Serbia": 6600, "Senegal": 8000, "Switzerland": 8000,
        "Mexico": 10000, "United States": 10000, "Poland": 10000,
        "Wales": 10000, "Canada": 15000, "Ecuador": 15000, "Ghana": 15000,
        "Morocco": 20000, "Cameroon": 25000, "Japan": 25000, "Qatar": 25000,
        "Tunisia": 30000, "South Korea": 30000, "Australia": 40000,
        "Costa Rica": 50000, "Saudi Arabia": 50000, "Iran": 500000,
    },
}

def odds_to_prob(american_odds):
    """Convert American odds to raw implied probability (not normalised)."""
    if american_odds > 0:
        return 100 / (100 + american_odds)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)

# ── Squad average age at tournament ───────────────────────────────────────────
# Source: Wikipedia WC squads pages, parsed via API, June 2026.
#   Age computed at tournament start date from player DOBs on Wikipedia.
#   2006/2010 pages use {{birth date and age2}} templates; 2014–2022 use wikitables.
#   2022 squads had 26 players (expanded from 23).
# FLAG: 2006 England (25.78) and Sweden (28.03) differ from press refs (27.40,
#   26.90) by >1 year — likely Wikipedia page updates since the press sources
#   were published. Trust Wikipedia values for the model.

WC_SQUAD_AGE = {
    2006: {
        "Angola": 26.66, "Argentina": 26.59, "Australia": 28.49,
        "Brazil": 28.75, "Costa Rica": 27.87, "Croatia": 27.97,
        "Czech Republic": 28.88, "Ecuador": 26.92, "England": 25.78,
        "France": 29.14, "Germany": 26.84, "Ghana": 25.15,
        "Iran": 27.09, "Italy": 28.72, "Ivory Coast": 25.93,
        "Japan": 27.75, "Mexico": 27.84, "Netherlands": 27.00,
        "Paraguay": 27.15, "Poland": 27.14, "Portugal": 28.38,
        "Saudi Arabia": 26.92, "Serbia and Montenegro": 28.28,
        "South Korea": 26.49, "Spain": 26.16, "Sweden": 28.03,
        "Switzerland": 25.64, "Togo": 25.95, "Trinidad and Tobago": 29.42,
        "Tunisia": 27.43, "Ukraine": 26.44, "United States": 28.65,
    },
    2010: {
        "Algeria": 26.71, "Argentina": 27.62, "Australia": 29.02,
        "Brazil": 29.16, "Cameroon": 25.59, "Chile": 26.36,
        "Denmark": 28.30, "England": 28.93, "France": 28.06,
        "Germany": 25.35, "Ghana": 24.72, "Greece": 28.09,
        "Honduras": 28.29, "Italy": 28.73, "Ivory Coast": 27.07,
        "Japan": 28.25, "Mexico": 27.57, "Netherlands": 28.10,
        "New Zealand": 27.87, "Nigeria": 26.25, "North Korea": 25.30,
        "Paraguay": 28.74, "Portugal": 28.24, "Serbia": 26.43,
        "Slovakia": 26.53, "Slovenia": 27.19, "South Africa": 27.31,
        "South Korea": 27.58, "Spain": 26.35, "Switzerland": 27.15,
        "United States": 27.27, "Uruguay": 27.08,
    },
    2014: {
        "Algeria": 26.59, "Argentina": 28.92, "Australia": 26.36,
        "Belgium": 25.93, "Bosnia and Herzegovina": 27.06, "Brazil": 28.36,
        "Cameroon": 26.60, "Chile": 27.99, "Colombia": 27.47,
        "Costa Rica": 27.43, "Croatia": 27.36, "Ecuador": 27.73,
        "England": 26.57, "France": 26.84, "Germany": 26.19,
        "Ghana": 25.45, "Greece": 28.51, "Honduras": 28.64,
        "Iran": 28.50, "Italy": 27.90, "Ivory Coast": 27.83,
        "Japan": 27.32, "Mexico": 27.26, "Netherlands": 26.47,
        "Nigeria": 25.63, "Portugal": 28.53, "Russia": 27.48,
        "South Korea": 26.19, "Spain": 28.25, "Switzerland": 26.07,
        "United States": 27.81, "Uruguay": 28.55,
    },
    2018: {
        "Argentina": 29.52, "Australia": 28.13, "Belgium": 27.59,
        "Brazil": 28.60, "Colombia": 28.39, "Costa Rica": 29.78,
        "Croatia": 27.90, "Denmark": 27.14, "Egypt": 28.98,
        "England": 26.05, "France": 26.03, "Germany": 27.14,
        "Iceland": 28.58, "Iran": 27.23, "Japan": 28.58,
        "Mexico": 29.24, "Morocco": 27.23, "Nigeria": 25.96,
        "Panama": 28.87, "Peru": 27.44, "Poland": 28.31,
        "Portugal": 28.37, "Russia": 28.84, "Saudi Arabia": 28.73,
        "Senegal": 26.99, "Serbia": 26.76, "South Korea": 27.79,
        "Spain": 28.49, "Sweden": 28.24, "Switzerland": 27.18,
        "Tunisia": 26.53, "Uruguay": 28.13,
    },
    2022: {
        "Argentina": 28.30, "Australia": 27.62, "Belgium": 28.35,
        "Brazil": 28.43, "Cameroon": 26.81, "Canada": 27.52,
        "Costa Rica": 27.68, "Croatia": 27.91, "Denmark": 27.68,
        "Ecuador": 26.07, "England": 26.96, "France": 27.11,
        "Germany": 27.32, "Ghana": 25.30, "Iran": 29.42,
        "Japan": 28.24, "Mexico": 28.97, "Morocco": 26.69,
        "Netherlands": 27.16, "Poland": 27.60, "Portugal": 27.32,
        "Qatar": 27.53, "Saudi Arabia": 27.82, "Senegal": 26.46,
        "Serbia": 27.36, "South Korea": 28.17, "Spain": 25.86,
        "Switzerland": 27.54, "Tunisia": 28.54, "United States": 25.59,
        "Uruguay": 28.31, "Wales": 26.87,
    },
}

def get_squad_age(team, wc_year):
    return WC_SQUAD_AGE.get(wc_year, {}).get(team)

# ── Squad average international caps per player ───────────────────────────────
# Source: Wikipedia WC squads pages, parsed via API, June 2026.
#   Caps extracted from squad templates (2006) or wikitable cells (2010–2022).

WC_SQUAD_CAPS = {
    2006: {
        "Angola": 19.4, "Argentina": 24.3, "Australia": 27.0,
        "Brazil": 43.8, "Costa Rica": 39.0, "Croatia": 32.7,
        "Czech Republic": 37.0, "Ecuador": 34.8, "England": 32.1,
        "France": 38.8, "Germany": 32.2, "Ghana": 16.8,
        "Iran": 36.8, "Italy": 32.9, "Ivory Coast": 23.1,
        "Japan": 45.6, "Mexico": 47.0, "Netherlands": 25.2,
        "Paraguay": 32.1, "Poland": 23.8, "Portugal": 34.5,
        "Saudi Arabia": 43.8, "Serbia and Montenegro": 27.0,
        "South Korea": 42.6, "Spain": 25.3, "Sweden": 39.4,
        "Switzerland": 23.4, "Togo": 21.0, "Trinidad and Tobago": 40.2,
        "Tunisia": 30.7, "Ukraine": 29.7, "United States": 44.8,
    },
    2010: {
        "Algeria": 21.0, "Argentina": 24.4, "Australia": 32.8,
        "Brazil": 38.7, "Cameroon": 29.6, "Chile": 24.7,
        "Denmark": 36.6, "England": 35.7, "France": 30.7,
        "Germany": 26.6, "Ghana": 23.7, "Greece": 30.7,
        "Honduras": 42.2, "Italy": 35.5, "Ivory Coast": 33.4,
        "Japan": 47.7, "Mexico": 43.3, "Netherlands": 35.9,
        "New Zealand": 21.5, "Nigeria": 25.9, "North Korea": 23.7,
        "Paraguay": 33.5, "Portugal": 29.1, "Serbia": 24.3,
        "Slovakia": 24.5, "Slovenia": 22.6, "South Africa": 32.6,
        "South Korea": 44.7, "Spain": 38.3, "Switzerland": 27.4,
        "United States": 35.3, "Uruguay": 23.0,
    },
    2014: {
        "Algeria": 16.6, "Argentina": 32.2, "Australia": 17.8,
        "Belgium": 32.6, "Bosnia and Herzegovina": 26.3, "Brazil": 29.7,
        "Cameroon": 30.2, "Chile": 35.0, "Colombia": 28.3,
        "Costa Rica": 34.0, "Croatia": 39.9, "Ecuador": 35.4,
        "England": 28.6, "France": 21.3, "Germany": 42.8,
        "Ghana": 30.7, "Greece": 38.8, "Honduras": 47.4,
        "Iran": 30.6, "Italy": 32.7, "Ivory Coast": 38.4,
        "Japan": 40.4, "Mexico": 41.2, "Netherlands": 28.7,
        "Nigeria": 28.2, "Portugal": 38.1, "Russia": 26.7,
        "South Korea": 26.4, "Spain": 60.5, "Switzerland": 32.2,
        "United States": 35.7, "Uruguay": 50.0,
    },
    2018: {
        "Argentina": 37.3, "Australia": 29.8, "Belgium": 47.3,
        "Brazil": 29.9, "Colombia": 31.0, "Costa Rica": 51.3,
        "Croatia": 40.3, "Denmark": 26.6, "Egypt": 37.3,
        "England": 21.0, "France": 26.0, "Germany": 41.1,
        "Iceland": 40.0, "Iran": 30.5, "Japan": 45.0,
        "Mexico": 60.3, "Morocco": 24.0, "Nigeria": 25.6,
        "Panama": 58.5, "Peru": 35.9, "Poland": 35.5,
        "Portugal": 39.5, "Russia": 28.5, "Saudi Arabia": 34.3,
        "Senegal": 26.6, "Serbia": 26.0, "South Korea": 29.3,
        "Spain": 42.2, "Sweden": 31.3, "Switzerland": 37.3,
        "Tunisia": 20.2, "Uruguay": 42.3,
    },
    2022: {
        "Argentina": 34.1, "Australia": 20.7, "Belgium": 52.2,
        "Brazil": 36.6, "Cameroon": 25.6, "Canada": 31.6,
        "Costa Rica": 44.3, "Croatia": 37.7, "Denmark": 38.6,
        "Ecuador": 24.3, "England": 31.5, "France": 34.3,
        "Germany": 35.2, "Ghana": 18.6, "Iran": 39.2,
        "Japan": 35.2, "Mexico": 50.7, "Morocco": 20.0,
        "Netherlands": 26.3, "Poland": 34.5, "Portugal": 41.1,
        "Qatar": 56.6, "Saudi Arabia": 28.8, "Senegal": 20.8,
        "Serbia": 29.8, "South Korea": 35.5, "Spain": 28.2,
        "Switzerland": 38.8, "Tunisia": 37.9, "United States": 26.3,
        "Uruguay": 45.5, "Wales": 38.1,
    },
}

def get_squad_caps(team, wc_year):
    return WC_SQUAD_CAPS.get(wc_year, {}).get(team)

# ── UCL players per WC squad ──────────────────────────────────────────────────
# Count of squad members whose club participated in the UCL group stage
# in the season immediately preceding each WC. Source: parse_wc_squads.py
# (Wikipedia squad pages cross-referenced against CL_CLUBS below).

WC_SQUAD_CL = {
    2006: {
        "Angola": 1, "Argentina": 10, "Australia": 3, "Brazil": 18,
        "Costa Rica": 0, "Croatia": 11, "Czech Republic": 6, "Ecuador": 0,
        "England": 16, "France": 15, "Germany": 10, "Ghana": 5,
        "Iran": 1, "Italy": 7, "Ivory Coast": 5, "Japan": 0,
        "Mexico": 2, "Netherlands": 15, "Paraguay": 3, "Poland": 1,
        "Portugal": 12, "Saudi Arabia": 0, "Serbia and Montenegro": 4,
        "South Korea": 1, "Spain": 13, "Sweden": 6, "Switzerland": 5,
        "Togo": 1, "Trinidad and Tobago": 1, "Tunisia": 3,
        "Ukraine": 1, "United States": 2,
    },
    2010: {
        "Algeria": 2, "Argentina": 11, "Australia": 1, "Brazil": 11,
        "Cameroon": 4, "Chile": 2, "Denmark": 6, "England": 9,
        "France": 22, "Germany": 10, "Ghana": 1, "Greece": 11,
        "Honduras": 0, "Italy": 8, "Ivory Coast": 7, "Japan": 2,
        "Mexico": 4, "Netherlands": 9, "New Zealand": 0, "Nigeria": 3,
        "North Korea": 0, "Paraguay": 1, "Portugal": 11, "Serbia": 6,
        "Slovakia": 3, "Slovenia": 1, "South Africa": 1, "South Korea": 1,
        "Spain": 16, "Switzerland": 1, "United States": 2, "Uruguay": 4,
    },
    2014: {
        "Algeria": 2, "Argentina": 11, "Australia": 1, "Belgium": 14,
        "Bosnia and Herzegovina": 4, "Brazil": 15, "Cameroon": 5,
        "Chile": 5, "Colombia": 3, "Costa Rica": 1, "Croatia": 6,
        "Ecuador": 1, "England": 11, "France": 13, "Germany": 18,
        "Ghana": 3, "Greece": 6, "Honduras": 2, "Iran": 0, "Italy": 10,
        "Ivory Coast": 4, "Japan": 2, "Mexico": 4, "Netherlands": 7,
        "Nigeria": 3, "Portugal": 9, "Russia": 9, "South Korea": 1,
        "Spain": 23, "Switzerland": 11, "United States": 1, "Uruguay": 8,
    },
    2018: {
        "Argentina": 14, "Australia": 2, "Belgium": 16, "Brazil": 18,
        "Colombia": 5, "Costa Rica": 3, "Croatia": 7, "Denmark": 5,
        "Egypt": 1, "England": 16, "France": 16, "Germany": 16,
        "Iceland": 0, "Iran": 2, "Japan": 1, "Mexico": 4, "Morocco": 4,
        "Nigeria": 2, "Panama": 0, "Peru": 1, "Poland": 6,
        "Portugal": 12, "Russia": 8, "Saudi Arabia": 0, "Senegal": 3,
        "Serbia": 5, "South Korea": 1, "Spain": 18, "Sweden": 3,
        "Switzerland": 6, "Tunisia": 0, "Uruguay": 7,
    },
    2022: {
        "Argentina": 16, "Australia": 0, "Belgium": 11, "Brazil": 17,
        "Cameroon": 4, "Canada": 6, "Costa Rica": 1, "Croatia": 9,
        "Denmark": 9, "Ecuador": 0, "England": 14, "France": 14,
        "Germany": 18, "Ghana": 4, "Iran": 1, "Japan": 1, "Mexico": 2,
        "Morocco": 6, "Netherlands": 19, "Poland": 4, "Portugal": 17,
        "Qatar": 0, "Saudi Arabia": 0, "Senegal": 4, "Serbia": 7,
        "South Korea": 0, "Spain": 21, "Switzerland": 7, "Tunisia": 0,
        "United States": 4, "Uruguay": 7, "Wales": 0,
    },
}

def get_squad_cl(team, wc_year):
    return WC_SQUAD_CL.get(wc_year, {}).get(team)

# ── UEFA Champions League group-stage clubs (season preceding each WC) ─────────
# Used to count CL players per WC squad (cross-reference squad club affiliations).
# Source: Wikipedia CL season pages (see URLs in DATA SOURCES header).
# Each entry is the 32 clubs that participated in the CL group stage that season.

CL_CLUBS = {
    2006: {  # 2005-06 UEFA CL (preceding 2006 WC)
        "Barcelona", "Real Madrid", "Villarreal", "Juventus", "AC Milan",
        "Inter Milan", "Chelsea", "Arsenal", "Liverpool", "Manchester United",
        "Bayern Munich", "PSV Eindhoven", "Ajax", "Benfica", "Porto",
        "Olympique Lyonnais", "Werder Bremen", "Schalke 04", "Club Brugge",
        "Rapid Vienna", "Panathinaikos", "Rangers", "Artmedia Bratislava",
        "Thun", "Udinese", "Anderlecht", "Rosenborg", "CSKA Moscow",
        "Fenerbahçe", "Sparta Prague", "Internazionale",
        "Olympiacos",
    },
    2010: {  # 2009-10 UEFA CL (preceding 2010 WC)
        "Barcelona", "Inter Milan", "Bayern Munich", "Manchester United",
        "Liverpool", "AC Milan", "Chelsea", "Real Madrid", "Marseille",
        "Porto", "Sevilla", "Wolfsburg", "Arsenal", "CSKA Moscow",
        "Olympique Lyonnais", "Bordeaux", "Fiorentina", "Beşiktaş",
        "Debrecen", "Unirea Urziceni", "VfL Wolfsburg", "Atlético Madrid",
        "Juventus", "Rubin Kazan", "Girondins de Bordeaux", "Panathinaikos",
        "AZ Alkmaar", "Olympiacos", "Standard Liège", "Rangers",
        "Apoel Nicosia", "Stuttgart",
    },
    2014: {  # 2013-14 UEFA CL (preceding 2014 WC)
        "Bayern Munich", "Atlético Madrid", "Chelsea", "Real Madrid",
        "Borussia Dortmund", "Paris Saint-Germain", "Manchester City",
        "Juventus", "Barcelona", "Arsenal", "Manchester United",
        "Porto", "Schalke 04", "AC Milan", "Benfica", "Shakhtar Donetsk",
        "BATE Borisov", "Galatasaray", "Victoria Plzeň", "Anderlecht",
        "Celtic", "Olympiacos", "Napoli", "Zenit Saint Petersburg",
        "CSKA Moscow", "Basel", "Real Sociedad", "Steaua București",
        "Leverkusen", "Marseille", "Ajax", "Vfl Wolfsburg",
    },
    2018: {  # 2017-18 UEFA CL (preceding 2018 WC)
        "Real Madrid", "Chelsea", "Barcelona", "Tottenham Hotspur",
        "Atlético Madrid", "Manchester City", "Bayern Munich",
        "Manchester United", "Paris Saint-Germain", "Juventus",
        "Sevilla", "Liverpool", "Roma", "Borussia Dortmund",
        "Basel", "Benfica", "Porto", "Leipzig", "Napoli",
        "Shakhtar Donetsk", "CSKA Moscow", "Spartak Moscow",
        "Anderlecht", "Celtic", "Feyenoord", "Maribor",
        "Qarabağ", "Sporting CP", "Olympiacos", "Besiktas",
        "APOEL", "Karabakh",
    },
    2022: {  # 2021-22 UEFA CL (preceding 2022 WC)
        "Chelsea", "Real Madrid", "Barcelona", "Sevilla",
        "Manchester City", "Manchester United", "Liverpool", "Bayern Munich",
        "Borussia Dortmund", "Inter Milan", "AC Milan", "Atalanta",
        "Juventus", "Paris Saint-Germain", "Ajax", "Benfica",
        "Porto", "Atlético Madrid", "Shakhtar Donetsk", "RB Leipzig",
        "Villarreal", "Sporting CP", "Salzburg", "Sheriff Tiraspol",
        "Club Brugge", "Young Boys", "Wolfsburg", "Besiktas",
        "Dynamo Kiev", "Zenit Saint Petersburg", "Malmo", "Lille",
    },
}

# ── Coach tenure at tournament (months in charge) ─────────────────────────────
# Sources:
#   2022 manager list: https://www.myfootballfacts.com/world-football/fifa/world-cup/fifa-world-cup-by-year/2022-fifa-world-cup-managers-list/
#   2022 appointment dates: https://www.goal.com/en-gb/lists/southgate-scaloni-managers-of-the-32-teams-that-will-play-in-2022-fifa-world-cup/blt0e70efc24ac7e79f
#   2018 manager list: https://worldsoccertalk.com/news/world-cup-2018-quick-look-32-managers-20180609-CMS-241763.html
#   Individual coach Wikipedia pages for appointment dates.
# tenure_months = months from appointment to tournament start (June 2018 / Nov 2022).
# FLAG: values marked * are estimates; verify against Wikipedia manager articles.

WC_COACHES = {
    2018: {
        # Tournament start: June 14 2018
        "Brazil":       {"name": "Tite",                   "appointed": "2016-07", "tenure_months": 23},
        "Germany":      {"name": "Joachim Löw",            "appointed": "2006-08", "tenure_months": 142},
        "Spain":        {"name": "Julen Lopetegui",        "appointed": "2016-07", "tenure_months": 23},
        "France":       {"name": "Didier Deschamps",       "appointed": "2012-07", "tenure_months": 71},
        "Argentina":    {"name": "Jorge Sampaoli",         "appointed": "2017-06", "tenure_months": 12},
        "Belgium":      {"name": "Roberto Martínez",       "appointed": "2016-08", "tenure_months": 22},
        "Portugal":     {"name": "Fernando Santos",        "appointed": "2014-09", "tenure_months": 45},
        "England":      {"name": "Gareth Southgate",       "appointed": "2016-11", "tenure_months": 19},
        "Uruguay":      {"name": "Óscar Tabárez",          "appointed": "2006-03", "tenure_months": 147},
        "Croatia":      {"name": "Zlatko Dalić",           "appointed": "2017-10", "tenure_months": 8},
        "Colombia":     {"name": "José Pékerman",          "appointed": "2012-01", "tenure_months": 77},
        "Poland":       {"name": "Adam Nawałka",           "appointed": "2013-10", "tenure_months": 56},
        "Switzerland":  {"name": "Vladimir Petković",      "appointed": "2014-07", "tenure_months": 47},
        "Iran":         {"name": "Carlos Queiroz",         "appointed": "2011-04", "tenure_months": 86},
        "Senegal":      {"name": "Aliou Cissé",            "appointed": "2015-01", "tenure_months": 41},
        "Denmark":      {"name": "Åge Hareide",            "appointed": "2016-07", "tenure_months": 23},
        "Mexico":       {"name": "Juan Carlos Osorio",     "appointed": "2015-11", "tenure_months": 31},
        "Russia":       {"name": "Stanislav Cherchesov",   "appointed": "2016-08", "tenure_months": 22},
        "Sweden":       {"name": "Janne Andersson",        "appointed": "2016-06", "tenure_months": 24},
        "Nigeria":      {"name": "Gernot Rohr",            "appointed": "2016-08", "tenure_months": 22},
        "Peru":         {"name": "Ricardo Gareca",         "appointed": "2015-03", "tenure_months": 39},
        "Costa Rica":   {"name": "Óscar Ramírez",          "appointed": "2015-07", "tenure_months": 35},
        "Egypt":        {"name": "Héctor Cúper",           "appointed": "2015-02", "tenure_months": 40},
        "Morocco":      {"name": "Hervé Renard",           "appointed": "2016-03", "tenure_months": 27},
        "Iceland":      {"name": "Heimir Hallgrímsson",    "appointed": "2016-05", "tenure_months": 25},
        "South Korea":  {"name": "Shin Tae-yong",          "appointed": "2017-07", "tenure_months": 11},  # *
        "Serbia":       {"name": "Mladen Krstajić",        "appointed": "2017-08", "tenure_months": 10},  # *
        "Tunisia":      {"name": "Nabil Maâloul",          "appointed": "2017-05", "tenure_months": 13},
        "Japan":        {"name": "Akira Nishino",          "appointed": "2018-04", "tenure_months": 2},
        "Panama":       {"name": "Hernán Darío Gómez",     "appointed": "2014-07", "tenure_months": 47},  # *
        "Saudi Arabia": {"name": "Juan Antonio Pizzi",     "appointed": "2017-12", "tenure_months": 6},
        "Australia":    {"name": "Bert van Marwijk",       "appointed": "2018-01", "tenure_months": 5},
    },
    2022: {
        # Tournament start: November 20 2022
        "France":       {"name": "Didier Deschamps",       "appointed": "2012-07", "tenure_months": 124},
        "England":      {"name": "Gareth Southgate",       "appointed": "2016-11", "tenure_months": 72},
        "Brazil":       {"name": "Tite",                   "appointed": "2016-07", "tenure_months": 76},
        "Spain":        {"name": "Luis Enrique",           "appointed": "2021-12", "tenure_months": 11},
        "Portugal":     {"name": "Fernando Santos",        "appointed": "2014-09", "tenure_months": 98},
        "Germany":      {"name": "Hansi Flick",            "appointed": "2021-08", "tenure_months": 15},
        "Argentina":    {"name": "Lionel Scaloni",         "appointed": "2018-11", "tenure_months": 48},
        "Netherlands":  {"name": "Louis van Gaal",         "appointed": "2021-08", "tenure_months": 15},
        "Belgium":      {"name": "Roberto Martínez",       "appointed": "2016-08", "tenure_months": 75},
        "Croatia":      {"name": "Zlatko Dalić",           "appointed": "2017-10", "tenure_months": 61},
        "Denmark":      {"name": "Kasper Hjulmand",        "appointed": "2020-06", "tenure_months": 29},
        "Switzerland":  {"name": "Murat Yakin",            "appointed": "2021-08", "tenure_months": 15},
        "United States":{"name": "Gregg Berhalter",        "appointed": "2018-12", "tenure_months": 47},
        "Morocco":      {"name": "Walid Regragui",         "appointed": "2022-08", "tenure_months": 3},
        "Senegal":      {"name": "Aliou Cissé",            "appointed": "2015-01", "tenure_months": 94},
        "Uruguay":      {"name": "Diego Alonso",           "appointed": "2022-01", "tenure_months": 10},
        "Poland":       {"name": "Czesław Michniewicz",    "appointed": "2022-01", "tenure_months": 10},
        "Serbia":       {"name": "Dragan Stojković",       "appointed": "2021-02", "tenure_months": 21},
        "Canada":       {"name": "John Herdman",           "appointed": "2018-01", "tenure_months": 58},
        "Japan":        {"name": "Hajime Moriyasu",        "appointed": "2018-08", "tenure_months": 51},
        "South Korea":  {"name": "Paulo Bento",            "appointed": "2018-09", "tenure_months": 50},
        "Mexico":       {"name": "Gerardo Martino",        "appointed": "2019-01", "tenure_months": 46},
        "Wales":        {"name": "Rob Page",               "appointed": "2020-11", "tenure_months": 24},
        "Ghana":        {"name": "Otto Addo",              "appointed": "2022-02", "tenure_months": 9},
        "Cameroon":     {"name": "Rigobert Song",          "appointed": "2022-02", "tenure_months": 9},
        "Ecuador":      {"name": "Gustavo Alfaro",         "appointed": "2020-01", "tenure_months": 34},
        "Australia":    {"name": "Graham Arnold",          "appointed": "2018-07", "tenure_months": 52},
        "Iran":         {"name": "Carlos Queiroz",         "appointed": "2019-09", "tenure_months": 38},
        "Tunisia":      {"name": "Jalel Kadri",            "appointed": "2021-12", "tenure_months": 11},
        "Costa Rica":   {"name": "Luis Fernando Suárez",   "appointed": "2021-08", "tenure_months": 15},
        "Qatar":        {"name": "Félix Sánchez",          "appointed": "2017-07", "tenure_months": 64},
        "Saudi Arabia": {"name": "Hervé Renard",           "appointed": "2019-08", "tenure_months": 39},
    },
    2006: {
        # Tournament start: June 9 2006. tenure_months from appointment to Jun 2006.
        # Sources: individual manager Wikipedia articles; * = estimate (±1 month).
        "Brazil":       {"name": "Carlos Alberto Parreira",  "appointed": "2003-07", "tenure_months": 35},
        "Italy":        {"name": "Marcello Lippi",           "appointed": "2004-08", "tenure_months": 22},
        "France":       {"name": "Raymond Domenech",         "appointed": "2004-07", "tenure_months": 23},
        "Argentina":    {"name": "José Pékerman",            "appointed": "2004-04", "tenure_months": 26},
        "England":      {"name": "Sven-Göran Eriksson",      "appointed": "2001-01", "tenure_months": 65},
        "Germany":      {"name": "Jürgen Klinsmann",         "appointed": "2004-07", "tenure_months": 23},
        "Netherlands":  {"name": "Marco van Basten",         "appointed": "2004-08", "tenure_months": 22},
        "Spain":        {"name": "Luis Aragonés",            "appointed": "2004-08", "tenure_months": 22},
        "Portugal":     {"name": "Luiz Felipe Scolari",      "appointed": "2002-10", "tenure_months": 44},
        "Czech Republic":{"name": "Karel Brückner",          "appointed": "2002-09", "tenure_months": 45},
        "Mexico":       {"name": "Ricardo La Volpe",         "appointed": "2002-12", "tenure_months": 42},
        "Ukraine":      {"name": "Oleg Blokhin",             "appointed": "2003-10", "tenure_months": 32},
        "Serbia and Montenegro": {"name": "Ilija Petković",  "appointed": "2003-09", "tenure_months": 33},
        "Switzerland":  {"name": "Jakob Kuhn",               "appointed": "2001-07", "tenure_months": 59},
        "Trinidad and Tobago": {"name": "Leo Beenhakker",    "appointed": "2004-02", "tenure_months": 28},  # *
        "Ghana":        {"name": "Ratomir Dujković",         "appointed": "2004-07", "tenure_months": 23},  # *
        "Ecuador":      {"name": "Luis Fernando Suárez",     "appointed": "2004-03", "tenure_months": 27},  # *
        "Paraguay":     {"name": "Aníbal Ruiz",              "appointed": "2003-07", "tenure_months": 35},  # *
        "South Korea":  {"name": "Dick Advocaat",            "appointed": "2005-05", "tenure_months": 13},  # *
        "Japan":        {"name": "Zico",                     "appointed": "2002-01", "tenure_months": 53},
        "Croatia":      {"name": "Zlatko Kranjčar",          "appointed": "2004-10", "tenure_months": 20},  # *
        "Australia":    {"name": "Guus Hiddink",             "appointed": "2005-10", "tenure_months": 8},
        "Iran":         {"name": "Branko Ivanković",         "appointed": "2002-09", "tenure_months": 45},  # *
        "Sweden":       {"name": "Lars Lagerbäck",           "appointed": "2000-01", "tenure_months": 77},  # sole mgr from 2004
        "Poland":       {"name": "Paweł Janas",              "appointed": "2003-01", "tenure_months": 41},  # *
        "Ivory Coast":  {"name": "Henri Michel",             "appointed": "2004-12", "tenure_months": 18},  # *
        "Togo":         {"name": "Otto Pfister",             "appointed": "2005-07", "tenure_months": 11},  # *
        "Angola":       {"name": "Luís Oliveira Gonçalves",  "appointed": "2003-07", "tenure_months": 35},  # *
        "Saudi Arabia": {"name": "Marcos Paquetá",           "appointed": "2005-06", "tenure_months": 12},  # *
        "Tunisia":      {"name": "Roger Lemerre",            "appointed": "2002-07", "tenure_months": 47},  # *
        "Costa Rica":   {"name": "Alexandre Guimarães",      "appointed": "2004-02", "tenure_months": 28},  # *
        "USA":          {"name": "Bruce Arena",              "appointed": "2006-01", "tenure_months": 5},
    },
    2010: {
        # Tournament start: June 11 2010. tenure_months from appointment to Jun 2010.
        "Spain":        {"name": "Vicente del Bosque",       "appointed": "2008-07", "tenure_months": 23},
        "Brazil":       {"name": "Dunga",                    "appointed": "2006-07", "tenure_months": 47},
        "Germany":      {"name": "Joachim Löw",              "appointed": "2006-08", "tenure_months": 46},
        "Argentina":    {"name": "Diego Maradona",           "appointed": "2008-11", "tenure_months": 19},
        "England":      {"name": "Fabio Capello",            "appointed": "2007-12", "tenure_months": 30},
        "France":       {"name": "Raymond Domenech",         "appointed": "2004-07", "tenure_months": 71},
        "Italy":        {"name": "Marcello Lippi",           "appointed": "2008-07", "tenure_months": 23},
        "Netherlands":  {"name": "Bert van Marwijk",         "appointed": "2008-02", "tenure_months": 28},
        "Portugal":     {"name": "Carlos Queiroz",           "appointed": "2008-07", "tenure_months": 23},
        "Uruguay":      {"name": "Óscar Tabárez",            "appointed": "2006-03", "tenure_months": 51},
        "USA":          {"name": "Bob Bradley",              "appointed": "2006-12", "tenure_months": 42},
        "Mexico":       {"name": "Javier Aguirre",           "appointed": "2009-04", "tenure_months": 14},
        "South Korea":  {"name": "Huh Jung-moo",             "appointed": "2007-11", "tenure_months": 31},
        "Japan":        {"name": "Takeshi Okada",            "appointed": "2007-12", "tenure_months": 30},
        "Australia":    {"name": "Pim Verbeek",              "appointed": "2007-10", "tenure_months": 32},
        "Ghana":        {"name": "Milovan Rajevac",          "appointed": "2008-08", "tenure_months": 22},
        "South Africa": {"name": "Carlos Alberto Parreira",  "appointed": "2009-06", "tenure_months": 12},
        "Nigeria":      {"name": "Lars Lagerbäck",           "appointed": "2010-03", "tenure_months": 3},
        "Greece":       {"name": "Otto Rehhagel",            "appointed": "2001-08", "tenure_months": 106},
        "Algeria":      {"name": "Rabah Saâdane",            "appointed": "2007-12", "tenure_months": 30},
        "Serbia":       {"name": "Radomir Antić",            "appointed": "2008-05", "tenure_months": 25},
        "Denmark":      {"name": "Morten Olsen",             "appointed": "2000-08", "tenure_months": 118},
        "Switzerland":  {"name": "Ottmar Hitzfeld",          "appointed": "2008-07", "tenure_months": 23},
        "Chile":        {"name": "Marcelo Bielsa",           "appointed": "2007-04", "tenure_months": 38},
        "Ivory Coast":  {"name": "Sven-Göran Eriksson",      "appointed": "2010-03", "tenure_months": 3},
        "Honduras":     {"name": "Reinaldo Rueda",           "appointed": "2006-09", "tenure_months": 45},
        "New Zealand":  {"name": "Ricki Herbert",            "appointed": "2005-07", "tenure_months": 59},
        "Paraguay":     {"name": "Gerardo Martino",          "appointed": "2006-11", "tenure_months": 43},
        "Slovakia":     {"name": "Vladimír Weiss Sr.",       "appointed": "2008-09", "tenure_months": 21},
        "Slovenia":     {"name": "Matjaž Kek",               "appointed": "2007-07", "tenure_months": 35},
        "North Korea":  {"name": "Kim Jong-hun",             "appointed": "2009-01", "tenure_months": 17},  # *
        "Cameroon":     {"name": "Paul Le Guen",             "appointed": "2009-06", "tenure_months": 12},
    },
    2014: {
        # Tournament start: June 12 2014. tenure_months from appointment to Jun 2014.
        "Germany":      {"name": "Joachim Löw",              "appointed": "2006-08", "tenure_months": 94},
        "Brazil":       {"name": "Luiz Felipe Scolari",      "appointed": "2012-11", "tenure_months": 19},
        "Argentina":    {"name": "Alejandro Sabella",        "appointed": "2011-08", "tenure_months": 34},
        "France":       {"name": "Didier Deschamps",         "appointed": "2012-07", "tenure_months": 23},
        "Spain":        {"name": "Vicente del Bosque",       "appointed": "2008-07", "tenure_months": 71},
        "Belgium":      {"name": "Marc Wilmots",             "appointed": "2012-05", "tenure_months": 25},
        "Colombia":     {"name": "José Pékerman",            "appointed": "2012-01", "tenure_months": 29},
        "Netherlands":  {"name": "Louis van Gaal",           "appointed": "2012-07", "tenure_months": 23},
        "England":      {"name": "Roy Hodgson",              "appointed": "2012-05", "tenure_months": 25},
        "Uruguay":      {"name": "Óscar Tabárez",            "appointed": "2006-03", "tenure_months": 99},
        "Italy":        {"name": "Cesare Prandelli",         "appointed": "2010-07", "tenure_months": 47},
        "Portugal":     {"name": "Paulo Bento",              "appointed": "2010-09", "tenure_months": 45},
        "Switzerland":  {"name": "Ottmar Hitzfeld",          "appointed": "2008-07", "tenure_months": 71},
        "Croatia":      {"name": "Niko Kovač",               "appointed": "2013-10", "tenure_months": 8},
        "Chile":        {"name": "Jorge Sampaoli",           "appointed": "2012-12", "tenure_months": 18},
        "Japan":        {"name": "Alberto Zaccheroni",       "appointed": "2010-08", "tenure_months": 46},
        "Russia":       {"name": "Fabio Capello",            "appointed": "2012-06", "tenure_months": 24},
        "Mexico":       {"name": "Miguel Herrera",           "appointed": "2013-10", "tenure_months": 8},
        "Costa Rica":   {"name": "Jorge Luis Pinto",         "appointed": "2011-09", "tenure_months": 33},
        "Greece":       {"name": "Fernando Santos",          "appointed": "2010-08", "tenure_months": 46},
        "Algeria":      {"name": "Vahid Halilhodžić",        "appointed": "2011-05", "tenure_months": 37},
        "Ecuador":      {"name": "Reinaldo Rueda",           "appointed": "2010-07", "tenure_months": 47},
        "Bosnia and Herzegovina": {"name": "Safet Sušić",    "appointed": "2012-03", "tenure_months": 27},
        "United States": {"name": "Jurgen Klinsmann",        "appointed": "2011-07", "tenure_months": 35},
        "Ghana":        {"name": "Kwesi Appiah",             "appointed": "2012-05", "tenure_months": 25},
        "South Korea":  {"name": "Hong Myung-bo",            "appointed": "2013-06", "tenure_months": 12},
        "Australia":    {"name": "Ange Postecoglou",         "appointed": "2013-10", "tenure_months": 8},
        "Nigeria":      {"name": "Stephen Keshi",            "appointed": "2011-11", "tenure_months": 31},
        "Iran":         {"name": "Carlos Queiroz",           "appointed": "2011-04", "tenure_months": 38},
        "Honduras":     {"name": "Luis Fernando Suárez",     "appointed": "2011-03", "tenure_months": 39},
        "Cameroon":     {"name": "Volker Finke",             "appointed": "2013-05", "tenure_months": 13},
        "Ivory Coast":  {"name": "Sabri Lamouchi",           "appointed": "2012-07", "tenure_months": 23},
    },
    2026: {
        # Tournament start: June 11 2026. tenure_months from appointment to Jun 2026.
        # Sources: FIFA.com, soccerphile.com/world-cup-2026/managers, club/FA announcements.
        # * = appointment date estimated to nearest month.
        # --- Group A ---
        "Mexico":                 {"name": "Javier Aguirre",        "appointed": "2024-07", "tenure_months": 23},
        "South Korea":            {"name": "Hong Myung-bo",          "appointed": "2024-07", "tenure_months": 23},
        "South Africa":           {"name": "Hugo Broos",             "appointed": "2021-05", "tenure_months": 61},
        "Czech Republic":         {"name": "Miroslav Koubek",        "appointed": "2025-12", "tenure_months": 6},
        # --- Group B ---
        "Canada":                 {"name": "Jesse Marsch",           "appointed": "2024-05", "tenure_months": 25},
        "Switzerland":            {"name": "Murat Yakin",            "appointed": "2021-08", "tenure_months": 58},
        "Qatar":                  {"name": "Julen Lopetegui",        "appointed": "2025-05", "tenure_months": 13},
        "Bosnia and Herzegovina": {"name": "Sergej Barbarez",        "appointed": "2024-04", "tenure_months": 26},
        # --- Group C ---
        "Brazil":                 {"name": "Carlo Ancelotti",        "appointed": "2025-05", "tenure_months": 13},
        "Morocco":                {"name": "Mohamed Ouahbi",         "appointed": "2026-03", "tenure_months": 3},  # *
        "Scotland":               {"name": "Steve Clarke",           "appointed": "2019-05", "tenure_months": 85},
        "Haiti":                  {"name": "Sébastien Migné",        "appointed": "2024-03", "tenure_months": 27},
        # --- Group D ---
        "United States":          {"name": "Mauricio Pochettino",    "appointed": "2024-09", "tenure_months": 21},
        "Australia":              {"name": "Tony Popovic",           "appointed": "2024-09", "tenure_months": 21},
        "Paraguay":               {"name": "Gustavo Alfaro",         "appointed": "2024-08", "tenure_months": 22},
        "Turkey":                 {"name": "Vincenzo Montella",      "appointed": "2023-09", "tenure_months": 33},
        # --- Group E ---
        "Germany":                {"name": "Julian Nagelsmann",      "appointed": "2023-09", "tenure_months": 33},
        "Ecuador":                {"name": "Sebastián Beccacece",    "appointed": "2024-08", "tenure_months": 22},
        "Ivory Coast":            {"name": "Emerse Faé",             "appointed": "2024-02", "tenure_months": 28},
        "Curaçao":                {"name": "Dick Advocaat",          "appointed": "2024-01", "tenure_months": 29},  # *
        # --- Group F ---
        "Netherlands":            {"name": "Ronald Koeman",          "appointed": "2023-01", "tenure_months": 41},
        "Japan":                  {"name": "Hajime Moriyasu",        "appointed": "2018-07", "tenure_months": 95},
        "Sweden":                 {"name": "Graham Potter",          "appointed": "2025-10", "tenure_months": 8},
        "Tunisia":                {"name": "Sabri Lamouchi",         "appointed": "2026-01", "tenure_months": 5},  # *
        # --- Group G ---
        "Belgium":                {"name": "Rudi Garcia",            "appointed": "2025-01", "tenure_months": 17},
        "Iran":                   {"name": "Amir Ghalenoei",         "appointed": "2023-03", "tenure_months": 39},
        "Egypt":                  {"name": "Hossam Hassan",          "appointed": "2024-02", "tenure_months": 28},  # *
        "New Zealand":            {"name": "Darren Bazeley",         "appointed": "2023-07", "tenure_months": 35},
        # --- Group H ---
        "Spain":                  {"name": "Luis de la Fuente",      "appointed": "2022-12", "tenure_months": 42},
        "Uruguay":                {"name": "Marcelo Bielsa",         "appointed": "2023-05", "tenure_months": 37},
        "Saudi Arabia":           {"name": "Giorgios Donis",         "appointed": "2026-04", "tenure_months": 2},   # *
        "Cape Verde":             {"name": "Bubista",                "appointed": "2020-01", "tenure_months": 77},
        # --- Group I ---
        "France":                 {"name": "Didier Deschamps",       "appointed": "2012-07", "tenure_months": 167},
        "Senegal":                {"name": "Pape Thiaw",             "appointed": "2024-12", "tenure_months": 18},
        "Iraq":                   {"name": "Graham Arnold",          "appointed": "2025-05", "tenure_months": 13},
        "Norway":                 {"name": "Ståle Solbakken",        "appointed": "2020-12", "tenure_months": 66},
        # --- Group J ---
        "Argentina":              {"name": "Lionel Scaloni",         "appointed": "2018-11", "tenure_months": 91},
        "Algeria":                {"name": "Vladimir Petković",      "appointed": "2024-02", "tenure_months": 28},
        "Austria":                {"name": "Ralf Rangnick",          "appointed": "2022-04", "tenure_months": 50},
        "Jordan":                 {"name": "Jamal Sellami",          "appointed": "2024-06", "tenure_months": 24},  # *
        # --- Group K ---
        "Portugal":               {"name": "Roberto Martínez",       "appointed": "2023-01", "tenure_months": 41},
        "Colombia":               {"name": "Néstor Lorenzo",         "appointed": "2022-06", "tenure_months": 48},
        "Uzbekistan":             {"name": "Fabio Cannavaro",        "appointed": "2025-10", "tenure_months": 8},
        "DR Congo":               {"name": "Sébastien Desabre",      "appointed": "2022-08", "tenure_months": 46},
        # --- Group L ---
        "England":                {"name": "Thomas Tuchel",          "appointed": "2025-01", "tenure_months": 17},
        "Croatia":                {"name": "Zlatko Dalić",           "appointed": "2017-10", "tenure_months": 104},
        "Ghana":                  {"name": "Carlos Queiroz",         "appointed": "2026-04", "tenure_months": 2},   # *
        "Panama":                 {"name": "Thomas Christiansen",    "appointed": "2020-07", "tenure_months": 71},
    },
    # For verification, full manager list across all WCs:
    #   https://grokipedia.com/page/List_of_managers_at_the_FIFA_World_Cup
}

def get_coach_tenure(team, wc_year):
    return WC_COACHES.get(wc_year, {}).get(team, {}).get("tenure_months")

# ── Confederation membership ──────────────────────────────────────────────────
# Simple lookup used as a categorical feature in the RF model.
# Australia moved from OFC to AFC in 2006; Serbia & Montenegro split after 2006.

WC_CONFEDERATION = {
    # UEFA
    "France": "UEFA", "Germany": "UEFA", "England": "UEFA", "Spain": "UEFA",
    "Italy": "UEFA", "Netherlands": "UEFA", "Portugal": "UEFA", "Belgium": "UEFA",
    "Croatia": "UEFA", "Serbia": "UEFA", "Denmark": "UEFA", "Switzerland": "UEFA",
    "Poland": "UEFA", "Russia": "UEFA", "Sweden": "UEFA", "Czech Republic": "UEFA",
    "Greece": "UEFA", "Ukraine": "UEFA", "Iceland": "UEFA", "Wales": "UEFA",
    "Turkey": "UEFA", "Slovakia": "UEFA", "Slovenia": "UEFA",
    "Bosnia and Herzegovina": "UEFA", "Serbia and Montenegro": "UEFA",
    "Scotland": "UEFA", "Norway": "UEFA", "Austria": "UEFA",
    # CONMEBOL
    "Brazil": "CONMEBOL", "Argentina": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Colombia": "CONMEBOL", "Chile": "CONMEBOL", "Paraguay": "CONMEBOL",
    "Peru": "CONMEBOL", "Ecuador": "CONMEBOL", "Bolivia": "CONMEBOL",
    # CONCACAF
    "Mexico": "CONCACAF", "United States": "CONCACAF", "USA": "CONCACAF",
    "Costa Rica": "CONCACAF", "Honduras": "CONCACAF", "Canada": "CONCACAF",
    "Panama": "CONCACAF", "Trinidad and Tobago": "CONCACAF",
    "Curaçao": "CONCACAF", "Haiti": "CONCACAF",
    # CAF
    "Morocco": "CAF", "Senegal": "CAF", "Ghana": "CAF", "Nigeria": "CAF",
    "Cameroon": "CAF", "Ivory Coast": "CAF", "Algeria": "CAF", "Tunisia": "CAF",
    "South Africa": "CAF", "Angola": "CAF", "Togo": "CAF", "Egypt": "CAF",
    "DR Congo": "CAF", "Cape Verde": "CAF",
    # AFC
    "Japan": "AFC", "South Korea": "AFC", "Iran": "AFC", "Saudi Arabia": "AFC",
    "Australia": "AFC", "Qatar": "AFC", "China": "AFC", "North Korea": "AFC",
    "Iraq": "AFC", "Uzbekistan": "AFC", "Jordan": "AFC",
    # OFC
    "New Zealand": "OFC",
}

# ── Host nation indicator ─────────────────────────────────────────────────────

WC_HOST = {
    2002: ["South Korea", "Japan"],
    2006: ["Germany"],
    2010: ["South Africa"],
    2014: ["Brazil"],
    2018: ["Russia"],
    2022: ["Qatar"],
}

def is_host(team, wc_year):
    return team in WC_HOST.get(wc_year, [])

# ── Covariates still to collect ───────────────────────────────────────────────
# STATUS as of June 2026:
#   ✓ FIFA rankings        — complete 2002–2022
#   ✓ GDP / population     — complete 2002–2022 (some 2002/2006 Nones)
#   ✓ Squad market value   — complete 2006–2022 (2002 missing)
#   ✓ Pre-tournament odds  — complete 2006/2014/2018/2022; 2010 partial (pre-qual)
#   ✓ Coach tenure         — complete 2006/2010/2014/2018/2022/2026 (some * estimates)
#   ✓ Confederation        — complete
#   ✓ Host indicator       — complete
#   ✓ Squad average age    — complete 2006–2022 (Wikipedia API, June 2026)
#   ✓ Squad avg caps       — complete 2006–2022 (Wikipedia API, June 2026)
#   ✓ CL players per squad — complete 2006–2022 (Wikipedia API + CL_CLUBS cross-ref)
#   ✓ Confederation        — complete (all 2026 teams including new entrants)
#
# STILL MISSING:
#
# 1. CL PLAYERS PER SQUAD (computed feature)
#    • Method: for each (team, wc_year), count players whose club at tournament
#      time appears in CL_CLUBS[wc_year].
#    • Requires squad club data — Wikipedia WC squads pages have it but the
#      parse script does not yet extract the club field. Needs a second pass.
#    • Big-5 players: same method but cross-reference against EPL/Bundesliga/
#      La Liga/Serie A/Ligue 1 clubs that season.
#
# 2. PRE-TOURNAMENT ODDS gaps
#    • 2010: missing ~9 confirmed qualifiers (teams not yet qualified Jul 2009).
#      Try Wayback Machine snapshot of Betfair/Pinnacle closer to Jun 11 2010.
#
# 3. 2002 SQUAD VALUES
#    • No archived Transfermarkt snapshot found. Impute or drop 2002 from training.
