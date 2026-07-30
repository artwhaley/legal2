# Retrieval hint investigation

Diagnostic comparison; this is not a statistical benchmark.

- Question: `When did we fight about school?`
- Frozen retrieval terms: `when did we fight about school, fight about school, school fight, when did we fight, we fought about school, argument about school, disagreement about school, school argument, school disagreement, when was the fight about school, date of school fight, school conflict, conflict about school, when did the school fight happen, school fight date, fight over school, school dispute, dispute about school, when did we argue about school, argue about school`
- Apples-to-apples validity: **True**

| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |
|---|---|---:|---:|---|
| semantic_ranges_censored | multi_window_ledger | 0/7 | 0 | `38f38a781b2a6cd62b3ed53fac6b757d9e6509f1e4ce2d0a78242db02626b922` |
| semantic_ranges | multi_window_ledger | 0/7 | 0 | `38f38a781b2a6cd62b3ed53fac6b757d9e6509f1e4ce2d0a78242db02626b922` |
| terms_only | multi_window_ledger | 0/7 | 0 | `38f38a781b2a6cd62b3ed53fac6b757d9e6509f1e4ce2d0a78242db02626b922` |

## Exact returned results

### semantic_ranges_censored

#### Synthesized answer

````text
No evidence of a fight about school was found in any of the five scanned windows (w000001 through w000005), which together cover the full supplied message range from decipher_message_1:7382 through decipher_export_5:142 (12,402 messages total). Across all windows, the conversation contains extensive school-related discussion — including school selection, applications, interviews, daily routines, gymnastics scheduling, school events, parent meetings, school photos, school sicknesses, school supplies, school friends, school performances, homeschool curriculum, and bullying at gymnastics — as well as other parenting disagreements concerning time-sharing and finances. However, none of the messages in any window describe a fight, argument, disagreement, or conflict between the speakers specifically about school, and no date or identifiable incident of a 'fight about school' is established in the supplied evidence. Because ledger_metadata contains no range IDs, no range dispositions are required.
````

#### Answer summary

````text
Across all five scanned windows covering the full supplied message range, no evidence was found of a fight about school between the speakers; the question cannot be answered from the supplied evidence.
````

#### Complete returned evidence ledger

````json
[]
````

#### Diagnostics, processing, coverage, and usage

````json
{
  "strategy": "multi_window_ledger",
  "uncertainties": [
    "No messages in any of the five scanned windows describe a fight, argument, disagreement, or conflict between the speakers about school.",
    "The supplied evidence does not establish any date or identifiable incident of a 'fight about school.'",
    "ledger_metadata is empty, so no range IDs were provided for disposition.",
    "It is unknown whether a 'fight about school' occurred outside the supplied message range."
  ],
  "coverage": {
    "evidence_range_count": 0,
    "message_count": 12402,
    "window_count": 5
  },
  "retrieval_diagnostics": {
    "final_ranges_outside_suggestions": 0,
    "final_ranges_overlapping_suggestions": 0,
    "mode": "semantic_ranges",
    "query_count": 20,
    "raw_hit_count": 1768,
    "selected_suggestion_message_count": 40,
    "suggestion_range_count": 40,
    "suggestions_without_final_evidence": 40,
    "unique_candidate_message_count": 361,
    "used_ranges_outside_suggestions": 0,
    "used_ranges_overlapping_suggestions": 0
  },
  "ledger_processing": {
    "compaction_applied": false,
    "compaction_group_calls": 0,
    "compaction_levels": 0,
    "direct_synthesis_input_tokens": 1280,
    "synthesis_usable_input_tokens": 244262
  },
  "usage": {
    "cost_complete": false,
    "currency": "USD",
    "estimated_cost": null,
    "input_tokens": 937538,
    "output_tokens": 817,
    "source": "provider_reported"
  }
}
````

### semantic_ranges

#### Synthesized answer

````text
No evidence was found in any of the five scanned windows (w000001 through w000005) describing a fight, argument, disagreement, or conflict between the participants about school. Across the entire scanned corpus, school-related discussion is limited to logistics (pickups, drop-offs, school events, school choice, schoolwork, school supplies, school forms, scheduling, curriculum, teachers, activities, gymnastics, medical/dental issues at school, custody-related school matters, and travel) and to general disagreements about education quality in the homeschooling context. No passage identifies a specific 'fight about school,' no such exchange is quoted or paraphrased, and no date is associated with such an event. Because ledger_metadata contains no range IDs, no range dispositions are required beyond noting that no evidence ranges were produced.
````

#### Answer summary

````text
Across all five scanned windows covering the full message corpus, there is no evidence of a fight about school between the participants; school-related content is confined to logistics and general education-quality discussion, with no dated argumentative exchange on that topic.
````

#### Complete returned evidence ledger

````json
[]
````

#### Diagnostics, processing, coverage, and usage

````json
{
  "strategy": "multi_window_ledger",
  "uncertainties": [
    "No evidence of a 'fight about school' was found in any scanned window; the question may refer to an event outside the supplied corpus or may conflate routine logistical school discussions with a conflict.",
    "Without ledger_metadata range IDs, no per-range dispositions can be assigned; the absence of evidence ranges is consistent with the coverage report's finding of zero evidence ranges across all windows.",
    "It is unclear whether the question refers to a specific past incident, a recurring pattern, or a general characterization of the participants' relationship regarding school matters."
  ],
  "coverage": {
    "evidence_range_count": 0,
    "message_count": 12402,
    "window_count": 5
  },
  "retrieval_diagnostics": {
    "final_ranges_outside_suggestions": 0,
    "final_ranges_overlapping_suggestions": 0,
    "mode": "semantic_ranges",
    "query_count": 20,
    "raw_hit_count": 2000,
    "selected_suggestion_message_count": 40,
    "suggestion_range_count": 40,
    "suggestions_without_final_evidence": 40,
    "unique_candidate_message_count": 397,
    "used_ranges_outside_suggestions": 0,
    "used_ranges_overlapping_suggestions": 0
  },
  "ledger_processing": {
    "compaction_applied": false,
    "compaction_group_calls": 0,
    "compaction_levels": 0,
    "direct_synthesis_input_tokens": 1217,
    "synthesis_usable_input_tokens": 244262
  },
  "usage": {
    "cost_complete": false,
    "currency": "USD",
    "estimated_cost": null,
    "input_tokens": 937484,
    "output_tokens": 770,
    "source": "provider_reported"
  }
}
````

### terms_only

#### Synthesized answer

````text
No evidence of a fight about school was found in any of the supplied windows (w000001 through w000005). Across all five scanned windows, which together cover the full message range from decipher_message_1:7382 through decipher_export_5:142 (a total of 12,402 messages), the participants discuss school-related topics including school selection, enrollment, school activities, school events, school pickup logistics, school-related health matters, school supplies, teachers, curriculum, schedules, gymnastics meets, homeschool curriculum, education neglect claims, and school bullying. However, no message in any window describes or refers to a specific fight, argument, or disagreement between the participants about school, and no date or occasion of such a fight is identified. The ledger_metadata contains no range IDs, so no range dispositions are required beyond noting that no evidence ranges were produced. The question 'When did we fight about school?' cannot be answered from the supplied evidence because the event itself is not documented in the scanned windows.
````

#### Answer summary

````text
No evidence of a fight about school was found in any of the five supplied windows covering all 12,402 messages; school-related discussion is present but no argument or fight about school is described, so the question cannot be answered from the available evidence.
````

#### Complete returned evidence ledger

````json
[]
````

#### Diagnostics, processing, coverage, and usage

````json
{
  "strategy": "multi_window_ledger",
  "uncertainties": [
    "No evidence of a fight about school was identified in any of the five scanned windows (w000001 through w000005), which collectively cover the entire supplied message range from decipher_message_1:7382 to decipher_export_5:142.",
    "The ledger_metadata is empty, so no range IDs were provided for disposition; it is unclear whether the absence of range IDs reflects that no evidence ranges were identified or that range metadata was not supplied.",
    "School-related topics are discussed extensively across the windows (school selection, enrollment, logistics, curriculum, teachers, schedules, gymnastics meets, homeschool curriculum, education neglect claims, school bullying), but none of these discussions are framed as a 'fight about school' with an identifiable date or occasion.",
    "It is possible that a fight about school occurred outside the supplied message range or was not captured in the scanned windows, but no such evidence is present in the supplied data."
  ],
  "coverage": {
    "evidence_range_count": 0,
    "message_count": 12402,
    "window_count": 5
  },
  "retrieval_diagnostics": {
    "final_ranges_outside_suggestions": 0,
    "final_ranges_overlapping_suggestions": 0,
    "mode": "terms_only",
    "query_count": 20,
    "raw_hit_count": 0,
    "selected_suggestion_message_count": 0,
    "suggestion_range_count": 0,
    "suggestions_without_final_evidence": 0,
    "unique_candidate_message_count": 0,
    "used_ranges_outside_suggestions": 0,
    "used_ranges_overlapping_suggestions": 0
  },
  "ledger_processing": {
    "compaction_applied": false,
    "compaction_group_calls": 0,
    "compaction_levels": 0,
    "direct_synthesis_input_tokens": 1256,
    "synthesis_usable_input_tokens": 244262
  },
  "usage": {
    "cost_complete": false,
    "currency": "USD",
    "estimated_cost": null,
    "input_tokens": 932542,
    "output_tokens": 930,
    "source": "provider_reported"
  }
}
````

