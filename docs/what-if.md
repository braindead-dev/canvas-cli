# What-If scores

[Coursework](coursework.md) · [Safety](safety.md)

Inspect, save or clear one hypothetical assignment-point score on your own existing submission. This is Canvas's saved What-If feature, not an official grade edit, coursework submission, attendance record or GPA prediction. New behavior is synthetic-tested, not live-write validated.

## Inspect or preview

```sh
canvas what-if 123 456 --format brief
canvas what-if-set 123 456 --score 85.5 --acknowledge-forecast-change
canvas what-if-set 123 456 --score 85.5 --include-forecasts --acknowledge-forecast-change
canvas what-if-clear 123 456 --acknowledge-forecast-change
```

Use assignment **points**, not a desired course percentage or letter grade. Finite negative and above-possible values are accepted because Canvas supports those hypothetical scenarios. Clearing sends explicit null, not zero. A missing own submission is unknown, not a zero score; the CLI does not create a submission or start an assessment to save a hypothesis.

Inspection uses fixed GraphQL metadata, not an assignment-view REST read or answers/feedback/official grade fields. A reported null means no saved hypothetical score on an accessible existing submission. Missing/malformed fields and foreign context are errors, not clearing or authority to write.

## Confirmation and readback

Writes require forecast acknowledgement even for preview. Previews bind identity, exact assignment/submission, policy, current attempt, saved hypothesis, proposed score and forecast-output opt-in. Review before repeating with `--yes --confirm DIGEST`.

The single-score native REST endpoint requires your own submission and submit permission. It updates only the selected hypothetical column and invokes native course recalculation, which can be costly. One write is followed by a separate exact own saved-score readback. No repeated scenario polling is provided.

Forecast values are omitted by default. `--include-forecasts` projects only native hypothetical current/final numeric totals; raw responses, assignment-group details and unrelated fields are discarded. Empty native forecast results remain empty, not zero or completed coursework. Returned forecasts are native responses, not independently recalculated or verified future grades; other saved hypotheses, grading rules, cached grading-period data, omissions and instructor adjustments can affect them.

Calculation can fail **after** the hypothetical column changed. Denied/malformed responses, changed context and unavailable readback report uncertainty rather than automatic retry or rollback. Inspect Canvas before repeating. Confirmation is not an atomic lock and does not independently prove that other saved hypotheses or official grade storage stayed unchanged.

## Whole-course inspection and reset

```sh
canvas what-if-course 123 --format brief
canvas what-if-reset 123 --acknowledge-all-what-if
canvas what-if-reset 123 --acknowledge-all-what-if --include-totals
```

Course inspection uses bounded GraphQL pagination for **your own active submissions on published assignments**, including unsubmitted rows. It selects no official grades, feedback, answers or unpublished content. Native permission, course/account changes, malformed data, foreign rows, duplicates, cursor loops and incomplete pagination fail closed. Even an empty reported inventory does not prove no saved hypotheses exist in hidden/historical rows.

Reset requires explicit whole-course acknowledgement even for preview and current native `reset_what_if_grades` permission on an available course. It sends one native bulk reset, not per-assignment clearing. This clears **all** own course hypotheses, including rows absent from the reported inventory, and updates timestamps on **every** own submission row, including already-clear ones. Confirmation binds the account, course, right, reported hypotheses and totals opt-in, not unseen storage or an atomic lock.

Independent readback verifies unchanged reported row metadata with cleared hypotheses only. **Hidden-row clearing remains unverified.** The native calculation response is projected only with `--include-totals`; it is not an independently verified stored official grade or a promised final result. Failure can follow bulk clearing, so do not automatically retry. No individual-score fallback, hidden-content reads, official-grade edits, coursework completion or rollback.

## Native contracts

[What-If API](https://developerdocs.instructure.com/services/canvas/resources/what_if_grades), [own/submit authorization and explicit null](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/what_if_grades_api_controller.rb), [column update and calculation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/services/submissions/what_if_grades_service.rb), [native grade calculator](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/grade_calculator.rb).

[Published-assignment/own-row resolver](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/course_type.rb), [explicit active submission states](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/graphql/types/submission_state_type.rb), [active-student reset right](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/models/course.rb).
