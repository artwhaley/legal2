# GLM 5.2 live run review

## Outcome

- Question: `Show me fights about school.`
- Model for planning, window extraction, and synthesis: `z-ai/glm-5.2`
- Strategy: `multi_window_ledger`
- Corpus: 12,402 messages; 720,646 preflight tokens
- Windows: 9
- Window evidence: 21 accepted ranges, 0 rejected, 0 normalized
- Provider retries or fallbacks: none
- Terminal result: `LEDGER_BIJECTION_FAILED`
- Request ID: `3880d2ea-f3d4-433f-a2ea-615f31328b1e`

The terminal error name is misleading. GLM returned every expected range ID exactly once and in the correct order. Validation failed because GLM emitted standalone findings for `r000004`, `r000005`, and `r000020` after classifying those same ranges as `useful_context`. The current findings contract requires every finding to cite at least one `direct_evidence` range.

## Timing and provider usage

- Planning: 35.9 seconds; 341 input tokens; 627 output tokens
- Nine window calls: 435,989 ms of provider latency in total; 957,137 input tokens; 7,543 output tokens
- Synthesis: 218.8 seconds; 68,832 input tokens; 4,865 output tokens
- Total LLM calls: 11
- Total provider-reported tokens: 1,026,310 input; 13,035 output
- End-to-end wall time: about 11 minutes 44 seconds

All nine windows completed on their first provider attempt. The synthesis provider call also completed on its first attempt; failure occurred only during deterministic validation of its returned JSON.

## Known-positive recall check

The extraction found six of the seven provisional known-positive dates:

| Known-positive date | Result |
|---|---|
| 2023-03-28 | Found (`r000007`, `r000008`) |
| 2023-11-13 | Found (`r000013`, `r000014`) |
| 2024-06-26 | Found (`r000016`) |
| 2024-07-10 | Found (`r000017`) |
| 2025-07-16 | Found (`r000018`) |
| 2025-08-04 | Missed |
| 2026-07-01 | Found (`r000021`) |

Semantic suggestions selected messages on all six of the known-positive dates that were found. The two 2025-08-04 candidates appeared only at ranks 65 and 95 for one retrieval query and did not make the 40-message fused suggestion set. The exhaustive scan then also missed that exchange.

This was not a suggestion-only scan: 7 of the 21 accepted ranges contained no selected suggestion message, while 14 contained at least one. The model demonstrably found evidence outside retrieval suggestions.

## Raw synthesized answer

The evidence contains 21 accepted ranges across 9 windows, identifying numerous disputes, arguments, and conflicts between Art Whaley and Julie Kramer (and, in some cases, between parents and third parties) that relate to schools, schooling, or education. The disputes span school safety policy, school selection, admissions, teacher/school governance conflicts, homeschool co-op operations, tuition, curriculum adequacy, education philosophy, and accusations of educational neglect. Below is a structured presentation of each identified fight or dispute, its nature, parties, form, and supporting range IDs.

1. Gun control and school safety policy debate (`r000001`): Following the Uvalde elementary school shooting, Art and Julie clash over opposing positions on gun control, arming teachers, and school-related violence prevention. Form: verbal/written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: primarily a policy debate rather than a personal conflict; parties largely agree on core concerns while differing on solutions.

2. School selection disagreement (`r000002`): Art and Julie express mild tension over school options for Olivia, including a Montessori in Norman requiring a long drive versus Wildflower Acton Academy. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: largely cooperative with mild friction over location and criteria; whether it rises to a "fight" is uncertain.

3. Kindergarten admissions anxiety and frustration (`r000003`): Art and Julie express shared frustration and hostility toward Wildflower school's admissions process while awaiting a decision. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: shared parental frustration directed at the school rather than a direct confrontation with the school.

4. Back-to-school night scheduling conflict (`r000004`): Julie and Art clash over a scheduling conflict between Wildflower's back-to-school night and a county fair dog show. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: resolved cooperatively; whether this constitutes a "fight" versus a scheduling disagreement is uncertain.

5. School pickup-line rules tension (`r000005`): Julie gives Art detailed instructions for school pickup procedures, implying tension about complying with school rules. Form: written instructions. Parties: Julie Kramer, Art Whaley. Uncertainty: latent tension rather than an active dispute.

6. Disagreement with school's evaluation of Olivia (`r000006`): Art and Julie both express disagreement with Wildflower's academic and behavioral assessment of Olivia. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: expressed between the parents rather than directly to the school.

7. Custody and financial dispute involving school tuition and school schedules (`r000007`): Julie and Art have a heated dispute over parenting time during spring break, escalating into financial responsibility, child support, private school tuition, and the impact of school schedules on parenting time. Form: verbal/written argument. Parties: Art Whaley, Julie Kramer. Uncertainty: primarily a parenting/financial dispute with school as one embedded topic.

8. School-choice and education-philosophy clash (`r000008`): Julie and Art debate private vs. public school, school quality, class sizes, education philosophy, reading and math instruction, and a teacher's decision about advancing Olivia. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: more cooperative in tone than the earlier custody argument; whether it rises to a "fight" is uncertain.

9. Wildflower school governance dispute with new owners (`r000009`): Julie reports parents' conflict with the new school owners over lack of transparency, teacher pay cuts, and leadership concerns, with discussion of forming a rival school. Form: written exchange (secondhand account). Parties: Parents (including Julie) vs. the Heinigers; Art engages as listener. Uncertainty: Julie's secondhand account; Julie says she does not know exactly what parents are mad about.

10. Jami/Spark Academy homeschool co-op conflict (`r000010`): Julie describes a major conflict with Jami, the LLC owner of the homeschool co-op, over education standards, bullying, curriculum, accountability, and school governance, resulting in the school dissolving. Form: written exchange (Julie's account). Parties: Parents vs. Jami; Art engages as questioner. Uncertainty: primarily Julie's perspective; Art's direct involvement is limited.

11. Firing of teachers and school selection debate (`r000011`): Julie announces firing Chris and Emily for failing to teach reading and core skills, followed by an extended debate over alternative schools and homeschooling. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: some parts are cooperative problem-solving rather than genuine conflict.

12. Sully inclusion debate (`r000012`): Art and Julie disagree over whether Sully, a pre-K child, should be included in the homeschool co-op, clashing over student mix, affordability, and educational fit. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: relatively mild and expressed with humor.

13. Tuition dispute with another family (`r000013`): Julie and Art discuss a conflict with another family over tuition payments for the homeschool co-op. Form: written exchange. Parties: Julie vs. the other family; Art agrees with Julie. Uncertainty: cooperative exchange about an external dispute rather than a fight between the messengers.

14. Homeschool co-op vs. home-based homeschooling debate (`r000014`): Art suggests discontinuing the co-op and homeschooling at home; Julie firmly pushes back, insisting on continuation. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: could be read as Art offering pragmatic advice rather than picking a fight.

15. Gymnastics competition argument (`r000015`): Julie and Art have a heated argument over whether Olivia should return to Julie's house the night before a gymnastics competition, escalating into accusations about priorities, financial investment, and Julie's history with gymnastics. Form: verbal/written argument. Parties: Art Whaley, Julie Kramer. Uncertainty: whether competitive gymnastics qualifies as school-related is uncertain.

16. Homeschool schedule dispute (`r000016`): Art and Julie disagree over Julie's plan to switch Olivia to a homeschool co-op schedule to accommodate morning gymnastics, clashing over instructional time, educational adequacy, and homeschool logistics. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: relatively civil; whether the tension constitutes a "fight" versus a disagreement is uncertain.

17. Theater arts camp vs. gymnastics scheduling dispute (`r000017`): Julie and Art disagree over whether Olivia should attend Art's theater arts camp or maintain her gymnastics schedule, with Art explicitly connecting the conflict to socialization concerns in "not real school." Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: centers on a summer camp rather than a school; the strength of the school connection is uncertain.

18. Education and gymnastics priority dispute (`r000018`): Art and Julie have a heated disagreement about whether Olivia's education is on track, whether the homeschool curriculum is adequate, whether gymnastics should be deprioritized until education improves, and the quality and purpose of public vs. homeschool education. Form: verbal/written argument. Parties: Art Whaley, Julie Kramer. Uncertainty: the dispute spans education and gymnastics finances intertwined; some messages in the range are not education-related.

19. Gymnastics enrollment injunction dispute (`r000019`): Julie accuses Art of violating a court injunction by withdrawing Olivia from her historical gymnastics enrollment and enrolling her elsewhere. Form: written accusation. Parties: Julie Kramer vs. Art Whaley. Uncertainty: whether gymnastics qualifies as school-related is uncertain; Julie frames it as a violation concerning an "educational facility and programs."

20. Art's deflection in custody/education exchange (`r000020`): Art deflects Julie's accusations about child support and a past warrant, stating he will not discuss the subject. Form: written exchange. Parties: Art Whaley, Julie Kramer. Uncertainty: does not independently address school or education; included only as part of the surrounding exchange about the injunction on educational enrollment.

21. Educational neglect accusations and curriculum dispute (`r000021`): Art demands final say over Olivia's activities and education, accusing Julie of neglecting her education and torturing her by not letting her quit gymnastics when bullied. Julie disputes these claims, details her educational involvement and financial investment, and attacks Art's competence in managing the online curriculum. Form: verbal/written argument. Parties: Art Whaley, Julie Kramer. Uncertainty: the range covers both education and extracurricular activities; some messages discuss gymnastics and bullying, which may or may not fall under the plan's definition of school.

Window coverage: All 9 windows were reviewed. Window `w000007` contained no evidence ranges meeting the plan criteria. Windows `w000001` through `w000006`, `w000008`, and `w000009` contained the 21 accepted ranges. Evidence validation was complete with 21 accepted ranges, 0 rejected ranges, and 0 normalized ranges.

## Raw answer summary

21 evidence ranges across 9 windows document school-related disputes between Art Whaley and Julie Kramer (and third parties) spanning school safety policy, school selection, admissions, teacher/school governance conflicts, homeschool co-op operations, tuition, curriculum adequacy, education philosophy, and accusations of educational neglect. Several ranges involve uncertainty about whether mild or borderline exchanges qualify as fights and whether gymnastics-related disputes are school-related.

## Engineering assessment

The planning call did the intended conceptual expansion correctly: it operationalized "fight" as arguments, disputes, clashes, and confrontations, and "school" as schooling, education, policy, administration, curriculum, and related matters.

The extraction path was reliable at the transport and schema levels and found substantial evidence outside semantic hints. Recall was strong but not complete against the seven provisional known positives (6/7).

The synthesis did distinguish stronger evidence from noise through dispositions: 18 ranges were marked `direct_evidence` and 3 were marked `useful_context`. However, its prose still promoted all 21 ranges into numbered findings, including the three it had classified as context. The deterministic validator correctly detected that internal contradiction, but incorrectly reports every such synthesis-contract failure as `LEDGER_BIJECTION_FAILED`, and the current all-or-nothing response discards 18 valid findings together with the 3 invalid ones.
