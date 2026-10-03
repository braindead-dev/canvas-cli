# Coursework

[Documentation](README.md) · [Safety](safety.md) · [Planning](planning.md)

## What needs attention?

```sh
canvas agenda --days 21 --include-undated --format brief
canvas work --course 123
canvas missing --course 123 --include-planner
canvas news --days 30 --format brief
```

| View | Purpose | Limit |
| --- | --- | --- |
| `deadlines` | Due dates within a window | Not unfinished status |
| `work` | Own status and effective due dates, including overrides | Missing status is unknown, not assumed unsubmitted |
| `agenda` | Unfinished dated work in local/IANA time | Urgency is time until due, not workload or grade impact |
| `missing` | Native missing-submission list | Empty is not all coursework complete |
| `overview` | Active courses, upcoming, todo, derived deadlines | External/course requirements can be omitted |

`work` includes dated/undated items by default; `--days` selects upcoming dated work. Agenda separates undated items and handles daylight saving per deadline.

Missing uses native submittable/current-grading-period filters. Listed locked work may not accept a late submission. Optional planner markers are checkboxes, not submissions.

Multi-course views report unavailable courses. Auth, rate-limit, network, malformed-response, and pagination failures are errors, not empty classes. These views cannot infer attendance, recurring meetings, reading, or external-tool requirements.

## Assignment and grade context

```sh
canvas assignment 123 456
canvas assignment-groups 123
canvas rubrics 123
canvas grades 123
```

Assignment groups expose native weights/rules; visible rubrics expose criteria. Grades select only the signed-in user and reject foreign user/course enrollments. Canvas controls visibility. Raw resource responses can contain private data.

## Own submissions and feedback

```sh
canvas submission 123 456
canvas submissions 123 --state submitted --include-history
canvas submissions 123 --include-rubric
canvas feedback 123 --format brief
canvas feedback 123 --include-text --since 2026-10-01T00:00:00Z
```

Single submission reads own status/comments/rubric. Bulk submissions paginate with the own numeric ID, never another student or `all`. Repeated assignment IDs/native state narrow scope. Foreign parents and malformed/truncated inventories fail.

Default bulk output is metadata. History adds attempt metadata; comments adds comment metadata; rubric adds indexed points/rating IDs. The broader content opt-in enables authorized work bodies, attachments, and fetched feedback text. Explicitly invisible/unpublished content is withheld. Unknown associations stay unknown.

Feedback is the feedback-only alternative. Text opt-in includes comment/rubric text, never own answers/history/media/providers/attachments. Criterion IDs are not descriptions; comments can be yours or peers', not just graders'.

Ordering is reassignment cues, earlier-attempt grades, then reported timestamps newest first. Raw scores/points are preserved without course-grade estimates. `grade_matches_current_submission=false` may mean an earlier attempt's grade.

The inclusive since filter requires seconds and an offset. Undated/uncertain feedback stays included and counted; this is not a complete change log. Time zone affects display, not due instants.

Reads never include `read_status`, submit, start attempts, or grade.

## Modules and quiz metadata

```sh
canvas outline 123
canvas module-progress 123 --format brief
canvas module-item 123 234 345 --format brief
canvas module-sequence 123 ModuleItem 345 --format brief
canvas module-sequence 123 Page welcome
canvas quizzes 123
canvas new-quizzes 123
```

Outline fetches module items separately because embedded lists may be capped/omitted. Progress preserves all/one rules and completed/incomplete/unknown/not-required states. Locked modules are not opened; denied item inventories remain partial. No explicit view/completion event is sent. Native evaluation can materialize/recalculate progression records.

Single-item inspection uses the complete paginated list, avoiding the single-item GET that can mark content read in Horizon courses. It checks the exact course/module/item and reports whitelisted metadata, requirements and a Canvas navigation link, not external launch URLs or content bodies. Locked content metadata can be reported without opening it. Missing completion is unknown.

Sequence returns native previous/current/next neighbors for a module-item ID or a File/Page/Discussion/Assignment/Quiz/ExternalTool asset. Page uses a URL slug, not an absolute URL. Prefer ModuleItem for one exact occurrence. Quiz/discussion items can point to an associated assignment; that ID is checked separately when needed. Canvas limits results to ten occurrences, which may be incomplete. Lock/completion status is not probed. Mastery-path flags/set IDs are metadata only; no path is chosen and no supplied content/launch URL is followed.

Classic quiz takes a quiz ID; New Quiz takes its assignment ID. Both expose metadata, never questions/attempts. Permissions/deployed engine can deny listings.

## Explicit module progress

```sh
canvas module-item-done 123 234 345 --acknowledge-module-progress
canvas module-item-not-done 123 234 345 --acknowledge-module-progress
canvas module-item-mark-read 123 234 345 --acknowledge-module-progress --acknowledge-content-viewed
```

These are [preview-first](safety.md#confirmation) own-student events. Done/not-done requires an actual reported `must_mark_done` checkbox, never a score/submission/contribution requirement. Mark-read is for content already accessed separately; the CLI does not open a page/file, launch LTI, or start a quiz. Only an actual `must_view` requirement can verify that read event's completion; otherwise the result explicitly says the stored view event is unverifiable.

Previews bind own identity, native participation permission, course, module policy and the full item inventory. A localized native “OK” is not proof: a separate paginated read verifies the selected requirement state and stable metadata. Unknown/malformed state, locks, truncated inventories, stale previews and already-selected checkbox states fail without an event. No automatic retry or rollback.

Done/not-done may sync your planner checkbox; completing a module can change downstream availability or publish an existing final grade to the SIS when configured. Policy is shown in the preview. Those downstream/planner/SIS effects are not independently verified, and confirmation is not an atomic lock. No shared module edits, assessment attempts, submissions or grade edits are requested.

## Mastery-path choices

```sh
canvas module-paths 123 234 345 --format brief
canvas module-path-select 123 234 345 678 --acknowledge-path-change
canvas module-path-select 123 234 345 679 --acknowledge-path-change --acknowledge-path-switch
```

Discovery reports your currently eligible native choices and their assignment IDs, not every instructor rule or future score range. Missing associations or processing flags remain unknown. Nested assignment models, submission answers and supplied launch URLs are not output. Assignment, graded quiz, discussion and page triggers are supported; linked pages are resolved through the paginated metadata list, not a page-view GET.

Selection is [preview-first](safety.md#confirmation) and restricted to the signed-in student. It requires an available course, native participation, exact module/item occurrence, eligible set, and your graded, posted trigger submission. Previews bind identity, complete module inventory, choices/associations and visible trigger grade. Truncated inventories, missing state, foreign parents and changed previews are refused before a POST. No quiz attempt or grade edit is sent.

Switching requires the additional acknowledgement even for a preview. This changes assignment overrides and can remove other assigned paths, retain shared assignments, affect submission availability, recalculate pacing dates and evaluate modules. The preview lists target IDs and conservative **potential** removals from other currently eligible choices; it cannot prove which other sets are assigned or which assignments Canvas will remove. Deleted/unpublished assignments may be omitted from the response.

A compound response acknowledges the request, not a stored choice. A separate own native sequence verifies a consistently reported selection among multiple eligible choices. Canvas infers a single eligible set ID automatically, so that case stays `accepted_choice_unverified` even if it reports selected. Old/unknown readback also stays unverified: changes may be delayed/cached, concurrent or unapplied. Inspect `module-paths` and Canvas before deciding what to do; the CLI never resends automatically. Missing processing is not “finished.” Assignment availability, due dates, downstream progress and configured SIS effects are not independently verified. Confirmation is not an atomic lock and there is no automatic rollback.

Already-reported choices are refused by default. Use `--reapply-selected-path` only to deliberately reapply that same set, including a pending single automatic path, after checking Canvas. This still requires the full assignment-change acknowledgement and a fresh preview/digest; it can recompute assignment overrides/dates and remove other assigned paths. It does not prove that a background job completed.

## Turn in work deliberately

```sh
canvas upload-assignment-file 123 456 --file paper.pdf
canvas submit-file 123 456 789
canvas submit-text 123 456 --text-file response.txt
canvas submit-url 123 456 --url-file project-url.txt
canvas submission-comment 123 456 --message-file question.txt
```

These start as previews; follow [confirmation](safety.md#confirmation). Upload stages a file, not a submission. Submit the returned file ID separately; multiple staged IDs are supported.

Previews check exact assignment, allowed type, publication/lock, account, destination, and content/file metadata. URL input is one absolute HTTP(S) URL read from a file. Plain text-entry/discussion input is escaped to HTML.

Comments are not submissions. Group/graded work may have a shared audience; review destination, content, and course rules. Canvas enforces final membership/acceptance. After uncertainty, check Canvas before repeating.

## Sources

[Assignments](https://developerdocs.instructure.com/services/canvas/resources/assignments), [Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions), [Modules](https://developerdocs.instructure.com/services/canvas/resources/modules), [New Quizzes](https://developerdocs.instructure.com/services/canvas/resources/new_quizzes).

[Native module events and Horizon reads](https://github.com/instructure/canvas-lms/blob/master/app/controllers/context_module_items_api_controller.rb), [Sequence association and ten-occurrence limit](https://github.com/instructure/canvas-lms/blob/master/app/helpers/application_helper.rb).

[Own eligible mastery sets and posted grades](https://github.com/instructure/canvas-lms/blob/master/app/models/conditional_release/service.rb), [Native switching, assignment overrides and pacing effects](https://github.com/instructure/canvas-lms/blob/master/app/models/conditional_release/override_handler.rb).
