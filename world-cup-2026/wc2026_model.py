"""
World Cup 2026 forecast — implementation based on the ranking-model engine of

    Groll, Ley, Schauberger & Van Eetvelde (2019),
    "A hybrid random forest to predict soccer matches in international tournaments",
    Journal of Quantitative Analysis in Sports 15(4):271-287  (doi:10.1515/jqas-2018-0060)
    [open-access predecessor: arXiv:1806.03208]

WHAT THIS IMPLEMENTS (faithfully):
  * The weighted Poisson "ranking" model (their Section 3.3, eqs. 4-5): each team gets a
    latent strength r_t estimated by *weighted* maximum likelihood, with two weight types:
        - time decay:      w_time = 0.5 ** (days_ago / half_period)     (half_period = 3 yrs)
        - match importance: w_type in {1 friendly, 2.5 qualifier, 3 continental final, 4 WC}
    log(lambda_ij) = beta0 + (r_i - r_j) + h * 1[i at home]
  * The Monte-Carlo tournament simulation (their Section 4): expected goals -> two independent
    Poisson draws per match, real 2026 group draw, real Round-of-32 bracket, extra time
    (goals x 0.33) and a coin-flip shootout, repeated many times for stage probabilities.

WHAT THIS DOES *NOT* IMPLEMENT:
  * The random-forest wrapper and its ~15 external covariates (GDP, population, bookmaker
    odds, squad market value / CL players, coach tenure, ...). The paper shows the team-ability
    parameter is BY FAR the most important predictor and the ranking model alone is roughly
    on par with the bookmakers (RPS 0.190 vs 0.188), so this engine captures the core. The
    forest mainly adds these abilities as a covariate on top. See README notes printed at end.
"""

import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.linear_model import PoissonRegressor
from scipy.optimize import linear_sum_assignment

RNG = np.random.default_rng(20260614)

# ----------------------------------------------------------------------------------
# 1. DATA + WEIGHTS
# ----------------------------------------------------------------------------------
HALF_PERIOD_DAYS = 3 * 365      # paper-selected best half period (~3 years)
WINDOW_YEARS     = 8            # paper estimates strengths on the previous 8 years
HOSTS            = {"United States", "Canada", "Mexico"}

def importance_weight(tournament: str) -> float:
    t = tournament.lower()
    if t == "fifa world cup":
        return 4.0
    if "qualification" in t or "qualifier" in t:
        return 2.5
    # continental finals + confed cup treated as importance 3
    finals = ["uefa euro", "copa am", "african cup of nations", "afc asian cup",
              "gold cup", "confederations", "nations league", "concacaf championship",
              "oceania nations"]
    if any(f in t for f in finals) and "qualification" not in t:
        return 3.0
    if t == "friendly":
        return 1.0
    return 1.5  # minor/regional tournaments

def load_matches(path="results.csv"):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["home_score", "away_score"]).copy()   # drop not-yet-played fixtures
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    return df

# ----------------------------------------------------------------------------------
# 2. WEIGHTED POISSON STRENGTH MODEL  (eqs. 4-5)
# ----------------------------------------------------------------------------------
def fit_strengths(df, ref_date, ridge=1e-4):
    cutoff = ref_date - pd.Timedelta(days=WINDOW_YEARS * 365)
    d = df[(df["date"] > cutoff) & (df["date"] <= ref_date)].copy()

    # two observations per match (stacked): attacker scores `goals` vs defender
    att   = pd.concat([d["home_team"], d["away_team"]], ignore_index=True)
    deff  = pd.concat([d["away_team"], d["home_team"]], ignore_index=True)
    goals = pd.concat([d["home_score"], d["away_score"]], ignore_index=True).astype(float).values
    home  = np.concatenate([np.where(d["neutral"], 0, 1), np.zeros(len(d))]).astype(float)

    # weights: time decay * match importance
    days  = np.concatenate([(ref_date - d["date"]).dt.days.values] * 2)
    w_time = 0.5 ** (days / HALF_PERIOD_DAYS)
    w_type = np.concatenate([d["tournament"].map(importance_weight).values] * 2)
    w = w_time * w_type

    teams = sorted(set(att)); T = len(teams)
    ai = pd.Categorical(att,  categories=teams).codes
    di = pd.Categorical(deff, categories=teams).codes
    n = len(att)
    rows = np.repeat(np.arange(n), 2)
    cols = np.empty(2 * n); vals = np.empty(2 * n)
    cols[0::2] = ai; vals[0::2] = 1.0     # +1 for attacking team  -> r_i
    cols[1::2] = di; vals[1::2] = -1.0    # -1 for defending team  -> - r_j
    X_team = sp.csr_matrix((vals, (rows, cols)), shape=(n, T))
    X = sp.hstack([sp.csr_matrix(home.reshape(-1, 1)), X_team]).tocsr()

    # tiny ridge stabilises strengths for teams with few matches (and centres them)
    m = PoissonRegressor(alpha=ridge, fit_intercept=True, max_iter=3000)
    m.fit(X, goals, sample_weight=w)

    beta0 = float(m.intercept_)
    home_eff = float(m.coef_[0])
    strengths = {t: float(m.coef_[1 + i]) for i, t in enumerate(teams)}
    return beta0, home_eff, strengths

# ----------------------------------------------------------------------------------
# 3. MATCH -> EXPECTED GOALS
# ----------------------------------------------------------------------------------
class Model:
    def __init__(self, beta0, home, strengths):
        self.b0, self.h, self.r = beta0, home, strengths
    def lambdas(self, a, b):
        ha = self.h if a in HOSTS else 0.0
        hb = self.h if b in HOSTS else 0.0
        la = np.exp(self.b0 + (self.r[a] - self.r[b]) + ha)
        lb = np.exp(self.b0 + (self.r[b] - self.r[a]) + hb)
        return la, lb

# ----------------------------------------------------------------------------------
# 3b. SINGLE-MATCH PREDICTIONS
# Given the two expected-goal values, the scoreline distribution is the outer product
# of two independent Poisson pmfs. From it we read off win/draw/loss and the single
# most likely exact score.
# ----------------------------------------------------------------------------------
from scipy.stats import poisson

def predict_match(model, a, b, max_goals=10):
    la, lb = model.lambdas(a, b)
    pa = poisson.pmf(np.arange(max_goals + 1), la)   # P(team a scores i)
    pb = poisson.pmf(np.arange(max_goals + 1), lb)   # P(team b scores j)
    M = np.outer(pa, pb)                             # joint scoreline matrix
    p_a   = np.tril(M, -1).sum()    # a scores more (i > j)
    p_draw = np.trace(M)            # i == j
    p_b   = np.triu(M, 1).sum()     # b scores more
    i, j = np.unravel_index(M.argmax(), M.shape)     # most likely exact score

    n = max_goals + 1
    idx = np.arange(n)

    # --- individual team goal lines: P(team scores >= k) for k=1,2,3,4 ---
    def team_overs(lam):
        return {f"over_{k-1}.5": float(1 - poisson.cdf(k - 1, lam)) for k in [1, 2, 3, 4]}

    # --- total goals lines: P(total goals >= k) for k=1..5 ---
    total_mask = idx[:, None] + idx[None, :]          # (i+j) matrix
    def total_overs():
        return {f"total_over_{k-1}.5": float(M[total_mask >= k].sum()) for k in [1, 2, 3, 4, 5]}

    # --- winning margin lines: P(A wins by >= k) and P(B wins by >= k) for k=1,2,3 ---
    # np.tril(M, -k).sum() = P(i - j >= k)  [A wins by at least k]
    # np.triu(M,  k).sum() = P(j - i >= k)  [B wins by at least k]
    def margin_overs():
        return {
            **{f"a_margin_over_{k-1}.5": float(np.tril(M, -k).sum()) for k in [1, 2, 3]},
            **{f"b_margin_over_{k-1}.5": float(np.triu(M,  k).sum()) for k in [1, 2, 3]},
        }

    return {"team_a": a, "team_b": b, "xg_a": la, "xg_b": lb,
            "p_a_win": p_a, "p_draw": p_draw, "p_b_win": p_b,
            "ml_score": f"{i}-{j}", "ml_score_prob": M[i, j],
            **{f"a_{k}": v for k, v in team_overs(la).items()},
            **{f"b_{k}": v for k, v in team_overs(lb).items()},
            **total_overs(),
            **margin_overs()}

def predict_group_matches(model):
    """Predict every group-stage fixture (all pairs within each group)."""
    rows = []
    for g, teams in GROUPS.items():
        for x in range(len(teams)):
            for y in range(x + 1, len(teams)):
                p = predict_match(model, teams[x], teams[y])
                rows.append([g, p["team_a"], p["team_b"],
                             round(p["xg_a"], 2), round(p["xg_b"], 2),
                             round(100 * p["p_a_win"], 1), round(100 * p["p_draw"], 1),
                             round(100 * p["p_b_win"], 1), p["ml_score"],
                             round(100 * p["ml_score_prob"], 1)])
    return pd.DataFrame(rows, columns=[
        "Group", "TeamA", "TeamB", "xG_A", "xG_B",
        "A win%", "Draw%", "B win%", "Likely score", "Score%"])

def predict_group_lines(model):
    """Over/under lines for every group fixture — goals and winning margins."""
    rows = []
    for g, teams in GROUPS.items():
        for x in range(len(teams)):
            for y in range(x + 1, len(teams)):
                p = predict_match(model, teams[x], teams[y])
                a, b = p["team_a"], p["team_b"]
                rows.append({
                    "Group": g, "TeamA": a, "TeamB": b,
                    "xG_A": round(p["xg_a"], 2), "xG_B": round(p["xg_b"], 2),
                    # individual team goal overs
                    "A >0.5g%": round(100 * p["a_over_0.5"], 1),
                    "A >1.5g%": round(100 * p["a_over_1.5"], 1),
                    "A >2.5g%": round(100 * p["a_over_2.5"], 1),
                    "A >3.5g%": round(100 * p["a_over_3.5"], 1),
                    "B >0.5g%": round(100 * p["b_over_0.5"], 1),
                    "B >1.5g%": round(100 * p["b_over_1.5"], 1),
                    "B >2.5g%": round(100 * p["b_over_2.5"], 1),
                    "B >3.5g%": round(100 * p["b_over_3.5"], 1),
                    # total goals overs
                    "Tot >0.5%": round(100 * p["total_over_0.5"], 1),
                    "Tot >1.5%": round(100 * p["total_over_1.5"], 1),
                    "Tot >2.5%": round(100 * p["total_over_2.5"], 1),
                    "Tot >3.5%": round(100 * p["total_over_3.5"], 1),
                    "Tot >4.5%": round(100 * p["total_over_4.5"], 1),
                    # winning margin overs
                    "A -0.5%":  round(100 * p["a_margin_over_0.5"], 1),
                    "A -1.5%":  round(100 * p["a_margin_over_1.5"], 1),
                    "A -2.5%":  round(100 * p["a_margin_over_2.5"], 1),
                    "B -0.5%":  round(100 * p["b_margin_over_0.5"], 1),
                    "B -1.5%":  round(100 * p["b_margin_over_1.5"], 1),
                    "B -2.5%":  round(100 * p["b_margin_over_2.5"], 1),
                })
    return pd.DataFrame(rows)

# ----------------------------------------------------------------------------------
# 4. 2026 TOURNAMENT STRUCTURE (real draw + real R32 bracket)
# ----------------------------------------------------------------------------------
ALIAS = {"Czechia": "Czech Republic", "USA": "United States",
         "Turkiye": "Turkey", "Curacao": "Curaçao"}
def canon(t): return ALIAS.get(t, t)

GROUPS = {
 "A": ["Mexico","South Korea","South Africa","Czechia"],
 "B": ["Canada","Switzerland","Qatar","Bosnia and Herzegovina"],
 "C": ["Brazil","Morocco","Scotland","Haiti"],
 "D": ["USA","Australia","Paraguay","Turkiye"],
 "E": ["Germany","Ecuador","Ivory Coast","Curacao"],
 "F": ["Netherlands","Japan","Sweden","Tunisia"],
 "G": ["Belgium","Iran","Egypt","New Zealand"],
 "H": ["Spain","Uruguay","Saudi Arabia","Cape Verde"],
 "I": ["France","Senegal","Iraq","Norway"],
 "J": ["Argentina","Algeria","Austria","Jordan"],
 "K": ["Portugal","Colombia","Uzbekistan","DR Congo"],
 "L": ["England","Croatia","Ghana","Panama"],
}
GROUPS = {g: [canon(t) for t in ts] for g, ts in GROUPS.items()}

# Round-of-32: (left, right). "W#"/"R#" = winner/runner-up of group #, "T<k>" = k-th assigned third.
# Third-place slots carry their FIFA allowed-group set.
THIRD_SLOTS = {  # match_id -> allowed groups
    74: set("ABCDF"), 77: set("CDFGH"), 79: set("CEFHI"), 80: set("EHIJK"),
    81: set("BEFIJ"), 82: set("AEHIJ"), 85: set("EFGIJ"), 87: set("DEIJL"),
}
R32 = {
 73:("R_A","R_B"), 74:("W_E","T74"), 75:("W_F","R_C"), 76:("W_C","R_F"),
 77:("W_I","T77"), 78:("R_E","R_I"), 79:("W_A","T79"), 80:("W_L","T80"),
 81:("W_D","T81"), 82:("W_G","T82"), 83:("R_K","R_L"), 84:("W_H","R_J"),
 85:("W_B","T85"), 86:("W_J","R_H"), 87:("W_K","T87"), 88:("R_D","R_G"),
}
R16 = {89:(74,77),90:(73,75),91:(76,78),92:(79,80),93:(83,84),94:(81,82),95:(86,88),96:(85,87)}
QF  = {97:(89,90),98:(91,92),99:(93,94),100:(95,96)}
SF  = {101:(97,98),102:(99,100)}
FINAL = (101,102)

# ----------------------------------------------------------------------------------
# 5. SIMULATION
# ----------------------------------------------------------------------------------
def simulate_once(model, group_goals, idx):
    # ---- group standings ----
    winners, runners = {}, {}
    thirds = []   # (group, pts, gd, gf, team)
    for g, teams in GROUPS.items():
        pts = {t:0 for t in teams}; gf={t:0 for t in teams}; ga={t:0 for t in teams}
        for (ga_, gb_, a, b) in group_goals[g]:
            sa, sb = a[idx], b[idx]
            gf[ga_]+=sa; ga[ga_]+=sb; gf[gb_]+=sb; ga[gb_]+=sa
            if sa>sb: pts[ga_]+=3
            elif sb>sa: pts[gb_]+=3
            else: pts[ga_]+=1; pts[gb_]+=1
        order = sorted(teams, key=lambda t:(pts[t], gf[t]-ga[t], gf[t], RNG.random()), reverse=True)
        winners[g], runners[g] = order[0], order[1]
        t3 = order[2]
        thirds.append((g, pts[t3], gf[t3]-ga[t3], gf[t3], t3))

    # ---- best 8 third-placed ----
    thirds.sort(key=lambda x:(x[1],x[2],x[3],RNG.random()), reverse=True)
    qual = thirds[:8]
    qual_groups = [q[0] for q in qual]
    third_team = {q[0]: q[4] for q in qual}

    # assign the 8 thirds to the 8 slots respecting allowed-group sets (bipartite matching)
    slot_ids = list(THIRD_SLOTS.keys())
    cost = np.ones((8,8))
    for i,s in enumerate(slot_ids):
        for j,grp in enumerate(qual_groups):
            if grp in THIRD_SLOTS[s]: cost[i,j]=0.0
    ri,cj = linear_sum_assignment(cost)
    slot_team = {slot_ids[i]: third_team[qual_groups[j]] for i,j in zip(ri,cj)}

    def resolve(tok):
        if tok.startswith("W_"): return winners[tok[2]]
        if tok.startswith("R_"): return runners[tok[2]]
        if tok.startswith("T"):  return slot_team[int(tok[1:])]
        return tok

    reached = {}  # team -> deepest stage index
    def mark(team, stage):
        if reached.get(team,0) < stage: reached[team]=stage
    # stage codes: 1=R32(played group, advanced), 2=R16, 3=QF, 4=SF, 5=Final, 6=Champion
    for g in GROUPS:
        mark(winners[g],1); mark(runners[g],1)
    for s in slot_team.values(): mark(s,1)

    def play_ko(a, b, stage_of_winner):
        la, lb = model.lambdas(a,b)
        sa, sb = RNG.poisson(la), RNG.poisson(lb)
        if sa==sb:  # extra time, shorter -> goals x0.33
            sa2, sb2 = RNG.poisson(la*0.33), RNG.poisson(lb*0.33)
            if sa2!=sb2:
                w = a if sa2>sb2 else b
            else:
                w = a if RNG.random()<0.5 else b   # coin-flip shootout (per paper)
        else:
            w = a if sa>sb else b
        mark(w, stage_of_winner)
        return w

    res = {}
    for mid,(L,Rr) in R32.items(): res[mid]=play_ko(resolve(L),resolve(Rr),2)
    for mid,(x,y) in R16.items(): res[mid]=play_ko(res[x],res[y],3)
    for mid,(x,y) in QF.items():  res[mid]=play_ko(res[x],res[y],4)
    for mid,(x,y) in SF.items():  res[mid]=play_ko(res[x],res[y],5)
    champ = play_ko(res[FINAL[0]],res[FINAL[1]],6)
    return reached

def run(model, n_sims=20000):
    # pre-draw all 72 group-match goals, vectorized over sims
    group_goals = {}
    for g, teams in GROUPS.items():
        fixtures=[]
        for i in range(len(teams)):
            for j in range(i+1,len(teams)):
                a,b = teams[i],teams[j]
                la,lb = model.lambdas(a,b)
                fixtures.append((a,b, RNG.poisson(la,n_sims), RNG.poisson(lb,n_sims)))
        group_goals[g]=fixtures

    stages=["R32","R16","QF","SF","Final","Champion"]
    counts={t:np.zeros(6) for g in GROUPS for t in GROUPS[g]}
    for k in range(n_sims):
        reached = simulate_once(model, group_goals, k)
        for t,s in reached.items():
            for si in range(s): counts[t][si]+=1
    rows=[]
    for t,c in counts.items():
        rows.append([t]+list(c/n_sims*100))
    out=pd.DataFrame(rows, columns=["Team"]+stages).sort_values("Champion",ascending=False)
    return out.reset_index(drop=True)

# ----------------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------------
if __name__ == "__main__":
    df = load_matches()
    ref_date = pd.Timestamp("2026-06-10")   # day before kickoff -> pre-tournament forecast
    print(f"Fitting weighted Poisson strength model on {WINDOW_YEARS}y window "
          f"(half-life {HALF_PERIOD_DAYS}d) up to {ref_date.date()} ...")
    beta0, home, strengths = fit_strengths(df, ref_date)
    print(f"  intercept beta0 = {beta0:+.3f}   home effect h = {home:+.3f}")
    model = Model(beta0, home, strengths)

    # strength ranking of the 48 finalists
    finalists = [t for g in GROUPS for t in GROUPS[g]]
    rank = sorted(finalists, key=lambda t: strengths.get(t,-9), reverse=True)
    print("\n=== Estimated team strength r_t (top 20 of the 48 finalists) ===")
    for i,t in enumerate(rank[:20],1):
        print(f"{i:2d}. {t:24s} {strengths.get(t,float('nan')):+.3f}")

    # example: expected goals for a single fixture
    a,b = "Spain","France"
    la,lb = model.lambdas(a,b)
    print(f"\nExample expected goals  {a} {la:.2f} - {lb:.2f} {b}")

    # ---- per-match predictions for every group fixture ----
    print("\n=== Individual group-match predictions (all 72 fixtures) ===")
    matches = predict_group_matches(model)
    pd.set_option("display.width", 140)
    print(matches.to_string(index=False))
    matches.to_csv("wc2026_match_predictions.csv", index=False)
    print("\nMatch predictions written to wc2026_match_predictions.csv")

    # ---- goal lines and margin lines ----
    print("\n=== Goal lines and winning-margin lines (all 72 fixtures) ===")
    lines = predict_group_lines(model)
    pd.set_option("display.width", 220)
    print(lines.to_string(index=False))
    lines.to_csv("wc2026_lines.csv", index=False)
    print("\nLines written to wc2026_lines.csv")

    # ---- predict any single matchup (e.g. a possible knockout tie) ----
    print("\n=== Example single-match breakdown (any matchup) ===")
    for (x, y) in [("Spain", "France"), ("Brazil", "England"), ("Argentina", "Portugal")]:
        p = predict_match(model, x, y)
        print(f"{x} vs {y}: xG {p['xg_a']:.2f}-{p['xg_b']:.2f} | "
              f"{x} win {100*p['p_a_win']:4.1f}%  draw {100*p['p_draw']:4.1f}%  "
              f"{y} win {100*p['p_b_win']:4.1f}%  | most likely {p['ml_score']} "
              f"({100*p['ml_score_prob']:.1f}%)")

    N=20000
    print(f"\nSimulating the tournament {N:,} times ...")
    table = run(model, N)
    pd.set_option("display.width",120)
    print("\n=== 2026 World Cup forecast (probabilities, %) ===")
    print(table.head(24).to_string(index=False, float_format=lambda x:f"{x:5.1f}"))
    table.to_csv("wc2026_forecast.csv", index=False)
    print("\nFull 48-team table written to wc2026_forecast.csv")
