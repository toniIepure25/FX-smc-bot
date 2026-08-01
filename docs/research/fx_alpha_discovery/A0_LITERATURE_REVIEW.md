# A0 Literature Review

Gate: `A0_INTRADAY_ALPHA_DISCOVERY_FACTORY_V1`

This review motivates tests only. It does not authorize changing a test after
observing outcomes.

## Microstructure And Order Flow

Evans and Lyons, "Order Flow and Exchange Rate Dynamics," Journal of Political
Economy, 2002, motivates the microstructure view that order flow can convey
information relevant to exchange-rate changes:
https://www.journals.uchicago.edu/doi/full/10.1086/324391

Evans, "FX Trading and Exchange Rate Dynamics," Journal of Finance, 2002,
motivates the idea that short-run exchange-rate dynamics can be tied to trading
information structure rather than only public macro news:
https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00501

Cheung and Chinn, NBER Working Paper 7416, documents practitioner views on
microstructure, spread conventions and limited intraday predictability:
https://www.nber.org/papers/w7416

## Intraday Momentum, Reversal And Session Structure

Elaut, Frommel and Lampaert, "Intraday momentum in FX markets," Journal of
Financial Markets, 2018, directly motivates session opening momentum and
liquidity-provider inventory hypotheses in FX:
https://www.sciencedirect.com/science/article/pii/S1386418116300313

Ito and Hashimoto, "Intraday seasonality in activities of the foreign exchange
markets," Journal of the Japanese and International Economies, 2006, motivates
timezone-aware session cells, quote revision intensity, volatility and spread
state:
https://www.sciencedirect.com/science/article/pii/S0889158306000463

## Spreads, Liquidity And Execution Costs

Pasquariello, "The Microstructure of Currency Markets," motivates intraday
spread and volatility state as market-condition variables:
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=252510

Ding, "The determinants of bid-ask spreads in the foreign exchange futures
market," motivates spread seasonality and links between spread, trade activity
and volatility:
https://ideas.repec.org/a/wly/jfutmk/v19y1999i3p307-324.html

## Cross-Pair And Triangular Relationships

Triangular consistency tests must be executable, not mid-price arbitrage claims.
Gençay and Gradojevic, "A new wavelet-based ultra-high-frequency analysis of
triangular currency arbitrage," Economic Modelling, 2020, motivates
triangular-residual features while warning that microstructure frictions matter:
https://www.sciencedirect.com/science/article/pii/S0264999318319072

## Multiple Testing And Backtest Overfitting

White, "A Reality Check for Data Snooping," Econometrica, 2000, motivates a
family-wide null over the full searched rule set:
https://doi.org/10.1111/1468-0262.00152

Hansen's Superior Predictive Ability test is included to reduce the penalty from
irrelevant poor alternatives while preserving multiple-testing discipline.

Bailey and Lopez de Prado, "The Deflated Sharpe Ratio," Journal of Portfolio
Management, 2014, and Bailey and Lopez de Prado, Significance, 2021, motivate
DSR and PBO controls:
https://www.econbiz.de/Record/the-deflated-sharpe-ratio-correcting-for-selection-bias-backtest-overfitting-and-non-normality-bailey-david/10011433463
https://rss.onlinelibrary.wiley.com/doi/10.1111/1740-9713.01588

## A0 Consequence

The A0 search space is broad but capped. Every candidate-equivalent attempt
counts toward the global budget. Profitable discovery backtests are insufficient
without internal confirmation, external validation and one-time independent
replication.
