# Editorial-value input contract

Run from `/home/test/media`, using `PYTHONPATH=/home/test/media/src` and
`python3 -m editor_assistant.workflow.cli`.

1. `live-evidence` registers source evidence as before. Preserve transcript/council
   source_type metadata. Read actual fact IDs from the stored packet.
2. Research/editor identifies 3–5 distinct topics and writes a JSON **list** of
   assessments to an absolute path. Each candidate has:
   - `angle_id`: unique non-empty string;
   - `title`: distinct topic title;
   - `reason`: short editorial judgment, including why readers should care or why not;
   - `fact_ids`: existing packet facts supporting this topic;
   - `scores`: all seven keys below, each containing an integer `score` (0, 1, 2).
     For every positive score, include `reason` and non-empty `fact_ids` that
     are a subset of the candidate's fact IDs.
3. Invoke `live-angles` with the evidence ID and the absolute assessment JSON path.
4. `NO_PUBLISHABLE_ANGLE` is a valid completed assessment: no article. A missing
   assessment is instead `ANGLE_REVIEW_REQUIRED`. Do not invent extra topics to
   meet the current minimum of three; escalate short transcripts for review.
5. For `ANGLE_SELECTED`, continue with explicit `live-case` VOICE/MODE selection
   and `live-generate`. A new assessment clears previous preparation. Existing
   cases cannot be silently rescored through this command.

## Rubric v1 (pilot, not calibrated)

| Key | Question |
|---|---|
| concrete_change | Is there a specific decision or change, not merely procedure? |
| people_impact | Who is affected, and how? |
| money_infrastructure_services | Is there a meaningful financial, infrastructure or service consequence? |
| different_positions | Is there a supported difference of positions, without manufactured conflict? |
| unexpected_fact | Is there a genuinely surprising supported fact? |
| strong_quote | Is there a meaningful sourced quote, not invented speech? |
| burgas_novelty | What is new and locally relevant for Burgas? |

0 = absent; 1 = limited; 2 = strong. Initial eligibility requires at least 5/14
and positive current Burgas novelty. The highest eligible total wins; ties use
angle_id order. This is an explicit pilot assumption needing editor calibration.
Assessments reference evidence but are not verified semantic truth. Citation
existence does not prove the score is justified. Keep decision vs discussion,
committee vs council, and historical vs current distinctions intact.

The persisted result lives in the evidence packet's `editorial_assessment`, not
in the SourceBundle candidate-discovery list. It contains all candidate scores,
reasons, selected angle, threshold and rubric version. Rejections also update
IdeaCard status. Selection restricts draft evidence to selected fact IDs;
unmapped meeting-wide quotes are omitted. Automatic transcript topic discovery
and model-based editorial scoring are not implemented by this narrow pass.

## Entertainment hook

Current prompt version: `m2.3b-prompt-2`. For EVENT_PREVIEW culture/comedy/
entertainment only, at most one light hook consistent with source tone and an
actual evidence synopsis. Then promptly give what/when/where, supported reader
interest, cast/program and practical details. Calendar-only material should stay
factual. No invented plot, reviews, reactions or audience promises. Rhetorical
questions do not excuse unsupported factual premises. Factual checking remains
mandatory; real editorial quality still needs human review.
