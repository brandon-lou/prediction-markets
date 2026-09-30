# World Cup 2026 forecast

A match and tournament model for the 2026 FIFA World Cup. It prices every group match (win/draw/loss,
exact scores, team and total goal lines, winning margins) and simulates the whole tournament.

The core replicates the ranking model from Groll, Ley, Schauberger & Van Eetvelde (2019), "A hybrid
random forest to predict soccer matches in international tournaments", *Journal of Quantitative
Analysis in Sports* 15(4). The notebook adds the paper's random-forest extension and scores the model
against real 2026 results.

## How it works

1. **Team strengths.** Every international match from the previous 8 years feeds a weighted Poisson
   regression, where λ<sub>ij</sub> is team i's expected goals against team j and r is each team's strength:

   ```
   log λ_ij = β0 + (r_i − r_j) + h · [i at home]
   ```

   Each match is weighted by recency (half-life 3 years) times importance (friendly 1, qualifier 2.5,
   continental final 3, World Cup 4). A tiny ridge penalty keeps teams with few matches stable. The
   three hosts get the home effect h in every match they play.
2. **Match prices.** Two independent Poisson draws give the full scoreline matrix. From it come
   win/draw/loss, the most likely score, each team's goals over 0.5 to 3.5, total goals over 0.5 to 4.5,
   and winning margins over 0.5 to 2.5.
3. **Tournament simulation.** 20,000 runs of the real 2026 format:
   - 12 groups, ranked by points, goal difference, then goals scored.
   - The 8 best third-placed teams go to the Round-of-32 slots FIFA allows for their group. The
     assignment is solved as a bipartite matching (`scipy.optimize.linear_sum_assignment`).
   - The real knockout bracket, with extra time at one third of the normal scoring rate and coin-flip
     shootouts, as in the paper.

   The output is each team's probability of reaching every round and of winning.

## The notebook

`wc2026_colab.ipynb` runs in Google Colab and adds:

- **A matchup explorer**: the most likely scorelines for any two teams.
- **Scoring against real results.** A clean pre-tournament fit (data through June 10, 2026) is scored
  on every completed 2026 match. Metrics: ranked probability score (a naive one-third each scores about
  0.222); errors in expected goals, total goals and margin; and how often the most likely exact score
  was right.
- **Live recalibration.** Refits through the current date, so tournament results update the strengths,
  and shows which teams moved most.
- **The paper's random-forest extension.** A random forest of 1,000 trees, split on Poisson deviance,
  using 21 features:
  - the ranking model's ability difference,
  - for each side: squad market value, average age and caps, Champions League players, GDP,
    population, FIFA ranking, bookmaker outright odds and coach tenure,
  - host and same-confederation flags.

  It trains on the 2006 to 2022 World Cups. If 2026 matches have been added to its training data, the
  evaluation cell warns that its scores are in-sample.

## Files

| file | contents |
|---|---|
| `wc2026_model.py` | the ranking model, match prices and tournament simulation, as a script |
| `wc2026_colab.ipynb` | the full workflow, including evaluation and the random forest |
| `wc_historical_data.py` | covariates for the 2002 to 2022 World Cups (the forest's training data), with sources and caveats |
| `covariates_2026.py` | the same covariates for the 48 teams of 2026, plus pre-tournament outright odds |
| `parse_wc_squads.py` | computes squad age, caps and Champions League counts from Wikipedia's squad pages |

## Running

```
pip install -r requirements.txt
curl -L -o results.csv https://raw.githubusercontent.com/martj42/international_results/master/results.csv
python wc2026_model.py
```

The script prints team strengths, all 72 group-match predictions and the tournament forecast. It
writes `wc2026_match_predictions.csv`, `wc2026_lines.csv` and `wc2026_forecast.csv`.

For the notebook, open it in Colab and run it top to bottom; it downloads the match data itself. The
random-forest cells ask you to upload `wc_historical_data.py` and `covariates_2026.py`.

## Data

- **Match results**: [martj42/international_results](https://github.com/martj42/international_results),
  every men's international since 1872.
- **Covariates**: sources are listed at the top of each data file. Values that are estimates are
  marked there.

## Limitations

- Goals are independent Poisson draws given the two strengths. There is no draw inflation (such as a
  Dixon–Coles correction) and no in-match dynamics.
- Shootouts are coin flips and extra time is a scaled-down match, following the paper.
- Some covariates are estimates, and the forest trains on only about 500 team-match rows.
