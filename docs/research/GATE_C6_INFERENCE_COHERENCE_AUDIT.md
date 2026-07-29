# Gate C6 Inference Coherence Audit

The validation absolute effect has a positive mean, a positive day-cluster bootstrap lower bound, and a sign-flip permutation p-value above 0.05. This is not necessarily a software contradiction because the procedures target different nulls and use different resampling structures.

The bootstrap interval summarizes mean uncertainty under day clustering. The sign-flip permutation checks a symmetry or exchangeability condition around zero using the frozen Monte Carlo implementation. Skew, heavy tails, within-day dependence, and unequal events per day can make those diagnostics diverge in finite samples.

Validation absolute mean: `11.33724832214778`

Bootstrap CI: `[0.7861459649301382, 22.05861848144365]`

Sign-flip p: `0.12843578210894552`

The preregistered intersection rule remains authoritative, so the absolute-effect criterion remains failed.
