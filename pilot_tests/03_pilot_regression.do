/*==============================================================================
  Pilot Test Regression — Layer 1 Mechanism Validation
  DV: official_cited (0/1)
  Treatment: treated (search_public_block = 1)
  Panel: 900 obs = 60 firms × 5 queries × 3 platforms
==============================================================================*/

clear all
set more off

* ── Load data ────────────────────────────────────────────────────────────────
import delimited "C:\Users\xl\OneDrive - Universitat Ramón Llull\bot_paper\pilot_tests\pilot_panel.csv", clear

* ── Variable prep ────────────────────────────────────────────────────────────
destring log_at roa leverage intan_ratio log_mkcap search_intensity, replace force

* Encode string variables for FE
encode platform, gen(platform_id)
encode query_id, gen(query_id_num)
encode ticker, gen(ticker_id)

* Label key variables
label variable official_cited "Official Site Cited (0/1)"
label variable treated "Treated (search_public_block=1)"
label variable n_sources "Number of Unique Sources Cited"
label variable log_at "Log Total Assets"
label variable roa "Return on Assets"
label variable leverage "Leverage"
label variable intan_ratio "Intangible Asset Ratio"
label variable log_mkcap "Log Market Cap"

* ── Summary stats ────────────────────────────────────────────────────────────
di as text _n "=== Summary Statistics ==="
tabstat official_cited n_sources, by(treated) stat(n mean sd) format(%9.3f)

di as text _n "=== By Platform ==="
table platform treated, stat(mean official_cited) stat(n official_cited) nformat(%9.3f)

* ── Regressions ──────────────────────────────────────────────────────────────
eststo clear

* Model 1: Pair FE + Query FE + Platform FE (baseline)
eststo m1: reghdfe official_cited treated, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* Model 2: + n_sources control
eststo m2: reghdfe official_cited treated n_sources, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* Model 3: + firm-level controls
eststo m3: reghdfe official_cited treated n_sources log_mkcap roa, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* Model 4: + all firm controls
eststo m4: reghdfe official_cited treated n_sources log_mkcap roa leverage intan_ratio, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* ── Display results ──────────────────────────────────────────────────────────
di as text _n "================================================================"
di as text "  MAIN RESULTS: Effect of robots.txt blocking on AI citation"
di as text "================================================================"

esttab m1 m2 m3 m4, ///
    se star(* 0.10 ** 0.05 *** 0.01) ///
    keep(treated n_sources log_mkcap roa leverage intan_ratio) ///
    label b(%9.4f) se(%9.4f) ///
    stats(N r2_within, labels("Observations" "Within R-sq") fmt(%9.0f %9.4f)) ///
    mtitles("Baseline" "+Sources" "+MktCap,ROA" "+AllControls") ///
    title("Table: Effect of AI Search Bot Blocking on Official Website Citation") ///
    addnotes("Pair FE, Query-type FE, and Platform FE absorbed in all models." ///
             "SE clustered at firm level.")

* ══════════════════════════════════════════════════════════════════════════════
*  HETEROGENEITY: Platform × Treatment interaction
* ══════════════════════════════════════════════════════════════════════════════
di as text _n "================================================================"
di as text "  HETEROGENEITY: Treatment effect by platform"
di as text "================================================================"

eststo clear

* Model 5: treated × platform interaction
eststo m5: reghdfe official_cited i.treated##i.platform_id n_sources, ///
    absorb(pair_id query_id_num) vce(cluster ticker_id)

esttab m5, se star(* 0.10 ** 0.05 *** 0.01) ///
    label b(%9.4f) se(%9.4f) ///
    stats(N r2_within, labels("Observations" "Within R-sq") fmt(%9.0f %9.4f)) ///
    title("Treatment × Platform Interaction")

* Marginal effects by platform
margins platform_id, dydx(treated) post
marginsplot, title("Treatment Effect by Platform") ///
    ytitle("Effect on P(Official Cited)") ///
    ylabel(-.3(.1).1) yline(0, lcolor(gs10) lpattern(dash))
graph export "C:\Users\xl\OneDrive - Universitat Ramón Llull\bot_paper\pilot_tests\fig_platform_heterogeneity.png", replace width(2400)

* ══════════════════════════════════════════════════════════════════════════════
*  HETEROGENEITY: Query type × Treatment interaction
* ══════════════════════════════════════════════════════════════════════════════
di as text _n "================================================================"
di as text "  HETEROGENEITY: Treatment effect by query type"
di as text "================================================================"

eststo clear

eststo m6: reghdfe official_cited i.treated##i.query_id_num n_sources, ///
    absorb(pair_id platform_id) vce(cluster ticker_id)

esttab m6, se star(* 0.10 ** 0.05 *** 0.01) ///
    label b(%9.4f) se(%9.4f) ///
    stats(N r2_within, labels("Observations" "Within R-sq") fmt(%9.0f %9.4f)) ///
    title("Treatment × Query Type Interaction")

* Marginal effects by query type
margins query_id_num, dydx(treated) post
marginsplot, title("Treatment Effect by Query Type") ///
    ytitle("Effect on P(Official Cited)") ///
    ylabel(-.4(.1).1) yline(0, lcolor(gs10) lpattern(dash))
graph export "C:\Users\xl\OneDrive - Universitat Ramón Llull\bot_paper\pilot_tests\fig_query_heterogeneity.png", replace width(2400)

* ══════════════════════════════════════════════════════════════════════════════
*  ALTERNATIVE DVs
* ══════════════════════════════════════════════════════════════════════════════
di as text _n "================================================================"
di as text "  ALTERNATIVE DVs"
di as text "================================================================"

eststo clear

* DV = official_rank_top3
eststo a1: reghdfe official_rank_top3 treated n_sources, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* DV = official_rank_inv
eststo a2: reghdfe official_rank_inv treated n_sources, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

* DV = n_sources (placebo: blocking shouldn't affect total sources)
eststo a3: reghdfe n_sources treated, ///
    absorb(pair_id query_id_num platform_id) vce(cluster ticker_id)

esttab a1 a2 a3, ///
    se star(* 0.10 ** 0.05 *** 0.01) ///
    keep(treated n_sources) ///
    label b(%9.4f) se(%9.4f) ///
    stats(N r2_within, labels("Observations" "Within R-sq") fmt(%9.0f %9.4f)) ///
    mtitles("Top3 Cited" "Inverse Rank" "N Sources (placebo)") ///
    title("Alternative Dependent Variables")

di as text _n "=== DONE ==="
