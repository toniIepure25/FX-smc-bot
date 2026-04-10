# Architecture Overview

## Mission

Build a research-grade, multi-pair FX trading framework that formalizes SMC/ICT concepts into systematic signals, supports portfolio-aware risk allocation, and remains extensible toward AI-assisted filtering and live deployment.

## Primary system blocks

1. **Data Core**
   - Multi-pair FX ingestion
   - Multi-timeframe synchronization
   - Session labeling and quality checks

2. **Structure Engine**
   - Swing detection
   - BOS / CHoCH
   - Liquidity pools
   - Displacement
   - Fair value gaps
   - Order blocks

3. **Alpha Layer**
   - Structured trade candidates
   - Signal scoring
   - Setup family classification

4. **Risk & Sizing**
   - Trade-level controls
   - Pair-level controls
   - Portfolio-level constraints
   - Volatility-aware and score-aware sizing

5. **Portfolio Engine**
   - Candidate ranking
   - Currency exposure limits
   - Correlation-aware allocation

6. **Execution & Simulation**
   - Spread/slippage modeling
   - Limit and stop logic
   - Event-driven backtesting

7. **ML Layer**
   - Regime filter
   - Trade quality model
   - Meta-labeling

8. **Research Analytics**
   - Attribution by pair, setup family, session, and regime
   - Walk-forward validation
   - Robustness and stress testing

## Initial implementation priority

- Typed configuration
- Core domain models
- Data contracts and loaders
- Structure engine primitives
- Trade candidate generation
- Risk and position sizing interfaces
- Portfolio selection interfaces

## Non-goals for the initial scaffold

- Live broker integration
- Full UI/dashboard
- Deep learning from raw candles
- Reinforcement learning
