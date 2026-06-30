# WML06 - Evaluation And Comparison

## Goal
Add evaluation and comparison tooling so strategies can be judged by quality and reliability.

## Depends On
- WML05

## Scope
- Implement `evaluator.py`.
- Evaluate each strategy output for:
  - parse success
  - answer range count
  - invalid message IDs
  - duplicate-looking ranges
  - represented source windows
  - likely dropped windows
  - output length
  - call count
  - latency
  - provider/model
- Add GUI view for evaluation report.
- Add `evaluation.md` output file.
- Add a comparison summary when multiple strategy outputs exist.

## Guardrails
- Evaluation can use deterministic checks, but it must not be framed as the final product answer.
- Do not mutate production state.

## Acceptance Criteria
- Evaluate Outputs button generates and displays evaluation.
- Output folder contains `evaluation.md`.
- Evaluation identifies whether all six source windows appear represented.

