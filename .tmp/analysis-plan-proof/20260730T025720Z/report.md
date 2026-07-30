# Frozen analysis-plan proof

This was a direct extraction diagnostic, not a full conversational-analysis
run. It replayed previously captured provider requests against the same model,
same assigned message window, same original IDs, same extraction response
contract, and same strict ledger validator. No retry or fallback was used.

The only change in each `current` arm was appending the frozen request-scoped
analysis plan recorded in the corresponding request artifact.

## Results

| Arm | Input | Settings | Time | Result |
|---|---:|---|---:|---|
| MiniMax plan/current | 187,224 tokens; 2,547 messages | temperature 0.1; no explicit reasoning override | 72.8s | HTTP 200; 4 ranges; strict validation passed |
| MiniMax plan/native probe | 187,234 tokens; 2,547 messages | temperature 1.0; top_p 0.95; requested thinking enabled | 67.6s | HTTP 200; 4 ranges; strict validation passed |
| Nemotron Ultra plan/current | 564,962 tokens; 6,007 messages | temperature 0.1; no explicit reasoning override | 197.2s | HTTP 200; 4 ranges; strict validation passed |

No arm needed endpoint-order normalization.

## MiniMax plan/current

The previous run of this same captured window returned no relevant evidence.
With only the analysis plan added, MiniMax returned four strictly valid ranges.
One range (`decipher_message_1:3529`) falls inside the known March 28, 2023
school-fight exchange.

The result is not yet high quality:

- ranges are single messages instead of complete exchanges;
- at least two selected messages are logistics or shared concern rather than a
  fight;
- the model recognized the broader March 28 conflict in `uncertainties` but did
  not return the complete range.

This proves that operational query planning materially corrected catastrophic
false negatives, but MiniMax still needs better range-selection discipline.

## MiniMax plan/native probe

The provider accepted `temperature=1.0`, `top_p=0.95`, and
`chat_template_kwargs.thinking_mode=enabled`. It returned no observable
`reasoning_content`, so this run does not prove that the hosted NIM backend
actually honored the thinking-mode control.

The output was not better than the current-settings arm. It again returned four
single-message ranges, explicitly described two as non-conflicts, and admitted
in `uncertainties` that it had found but omitted the broader March 28 fight.

## Nemotron Ultra plan/current

The previous run of this same captured window found relevant material but
failed strict validation with unknown or fabricated IDs. With only the analysis
plan added, Ultra returned four substantial ranges, all using real IDs in valid
array order:

1. `decipher_message_1:987` through `decipher_message_1:970`
2. `decipher_export_19:576` through `decipher_export_19:608`
3. `decipher_export_19:3370` through `decipher_export_19:3398`
4. `decipher_export_5:135` through `decipher_export_5:142`

These overlap four known-positive ranges. Ultra also returned 20,543 characters
of provider-visible reasoning content under the current settings, demonstrating
that lack of reasoning mode was not the cause of its prior failure.

## Conclusion

The missing operational analysis plan was the primary defect exposed by these
models. It changed MiniMax from an empty result to valid evidence and changed
Ultra from unusable identity output to four substantial, strictly valid ranges.

Model-native reasoning and sampling settings are not a prerequisite for
rebuilding the planning path:

- Ultra was already reasoning under current settings.
- MiniMax succeeded without observable reasoning once it received a plan.
- MiniMax's nominal native-settings arm did not improve selection or range
  boundaries.

Reasoning controls should still become typed, admin-visible model-profile
settings later, but they should be evaluated independently after the analysis
planning contract is implemented.

## Artifacts

- `minimax-current-request.json`
- `minimax-current-result.json`
- `minimax-native-request.json`
- `minimax-native-result.json`
- `ultra-current-request.json`
- `ultra-current-result.json`
