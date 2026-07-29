# Acceptance Research Results

## 1. Data Certification

USDJPY development data were frozen for 2015-2019. Validation data were recertified for 2020-2022 after provider remediation.

## 2. Development Event Counts

Common-protocol development matched events: `2440`.

## 3. Development Primary Effects

Event `-3.66885245901655`, control `-17.33688524590164`, differential `13.668032786885094`, p `0.006496751624187906`, CI `[6.277491118674749, 21.844720075312043]`.

## 4. Internal Temporal Replication

C4-B preserved discovery differential `18.22368421052636` and internal replication differential `7.2751004016060214`.

## 5. Mechanism Redesign

C4-B separated absolute event response from relative resilience.

## 6. Validation Matching and Balance

Validation matched events: `1192`; exact-key relaxations: `0`; balance requirements passed.

## 7. Validation Relative Effect

Event `11.33724832214778`, control `-16.11577181208039`, differential `27.453020134228165`, p `0.004497751124437781`, CI `[14.784214406740844, 40.27386831699497]`.

## 8. Validation Absolute Effect

Absolute mean `11.33724832214778`, sign-flip p `0.12843578210894552`, CI `[0.7861459649301382, 22.05861848144365]`. This failed the full preregistered rule.

## 9. Placebo

The shifted placebo did not reproduce the relative-resilience effect.

## 10. Annual Stability

Validation annual effects: `{'2020': {'absolute_control_executable_markout': -25.339195979899877, 'absolute_event_executable_markout': 12.979899497487537, 'bootstrap_ci': [17.90121291098714, 58.77744542259522], 'eligible_events': 398, 'event_minus_control_differential': 38.31909547738741, 'matched_events': 398}, '2021': {'absolute_control_executable_markout': -13.368811881187654, 'absolute_event_executable_markout': 2.935643564356629, 'bootstrap_ci': [4.694096656406014, 29.578429729323833], 'eligible_events': 404, 'event_minus_control_differential': 16.30445544554428, 'matched_events': 404}, '2022': {'absolute_control_executable_markout': -9.548717948717599, 'absolute_event_executable_markout': 18.36410256410265, 'bootstrap_ci': [-1.6567207366227235, 58.58885648250037], 'eligible_events': 390, 'event_minus_control_differential': 27.912820512820243, 'matched_events': 390}}`.

## 11. Mechanism Transition

Event markout changed by `15.00610078116433`, control markout by `1.2211134338212517`, and differential by `13.78498734734307`.

## 12. Transport Standardization

Standardized validation event `12.26554243296961`, standardized differential `35.53894763198631`, maximum weight / median `10.399999999999999`.

## 13. Failed Candidate Criteria

Failed criteria: absolute-effect inference and valid transport standardization.

## 14. Final Research Decision

`ACCEPTANCE_RESEARCH_PROGRAM_CLOSED_WITH_MIXED_NONTRANSPORTABLE_RESULT`.
