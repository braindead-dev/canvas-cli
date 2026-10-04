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

The native REST endpoint requires your own submission and submit permission. It updates only the selected hypothetical column and invokes native course recalculation, which can be costly. One write is followed by a separate exact own saved-score readback. No course-wide reset or repeated scenario polling is provided.

Forecast values are omitted by default. `--include-forecasts` projects only native hypothetical current/final numeric totals; raw responses, assignment-group details and unrelated fields are discarded. Empty native forecast results remain empty, not zero or completed coursework. Returned forecasts are native responses, not independently recalculated or verified future grades; other saved hypotheses, grading rules, cached grading-period data, omissions and instructor adjustments can affect them.

Calculation can fail **after** the hypothetical column changed. Denied/malformed responses, changed context and unavailable readback report uncertainty rather than automatic retry or rollback. Inspect Canvas before repeating. Confirmation is not an atomic lock and does not independently prove that other saved hypotheses or official grade storage stayed unchanged.

## Native contracts

[What-If API](https://developerdocs.instructure.com/services/canvas/resources/what_if_grades), [own/submit authorization and explicit null](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/what_if_grades_api_controller.rb), [column update and calculation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/services/submissions/what_if_grades_service.rb), [native grade calculator](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/lib/grade_calculator.rb).
