# Coursework

[Documentation](README.md) · [Safety](safety.md) · [Planning](planning.md)

## What needs attention?

```sh
canvas-pocket agenda --days 21 --include-undated --format brief
canvas-pocket work --course 123
canvas-pocket missing --course 123 --include-planner
canvas-pocket news --days 30 --format brief
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
canvas-pocket assignment 123 456
canvas-pocket assignment-groups 123
canvas-pocket rubrics 123
canvas-pocket grades 123
```

Assignment groups expose native weights/rules; visible rubrics expose criteria. Grades select only the signed-in user and reject foreign user/course enrollments. Canvas controls visibility. Raw resource responses can contain private data.

## Own submissions and feedback

```sh
canvas-pocket submission 123 456
canvas-pocket submissions 123 --state submitted --include-history
canvas-pocket submissions 123 --include-rubric
canvas-pocket feedback 123 --format brief
canvas-pocket feedback 123 --include-text --since 2026-10-01T00:00:00Z
```

Single submission reads own status/comments/rubric. Bulk submissions paginate with the own numeric ID, never another student or `all`. Repeated assignment IDs/native state narrow scope. Foreign parents and malformed/truncated inventories fail.

Default bulk output is metadata. History adds attempt metadata; comments adds comment metadata; rubric adds indexed points/rating IDs. The broader content opt-in enables authorized work bodies, attachments, and fetched feedback text. Explicitly invisible/unpublished content is withheld. Unknown associations stay unknown.

Feedback is the feedback-only alternative. Text opt-in includes comment/rubric text, never own answers/history/media/providers/attachments. Criterion IDs are not descriptions; comments can be yours or peers', not just graders'.

Ordering is reassignment cues, earlier-attempt grades, then reported timestamps newest first. Raw scores/points are preserved without course-grade estimates. `grade_matches_current_submission=false` may mean an earlier attempt's grade.

The inclusive since filter requires seconds and an offset. Undated/uncertain feedback stays included and counted; this is not a complete change log. Time zone affects display, not due instants.

Reads never include `read_status`, submit, start attempts, or grade.

## Modules and quiz metadata

```sh
canvas-pocket outline 123
canvas-pocket module-progress 123 --format brief
canvas-pocket quizzes 123
canvas-pocket new-quizzes 123
```

Outline fetches module items separately because embedded lists may be capped/omitted. Progress preserves all/one rules and completed/incomplete/unknown/not-required states. Locked modules are not opened; denied item inventories remain partial. No view/completion event is sent.

Classic quiz takes a quiz ID; New Quiz takes its assignment ID. Both expose metadata, never questions/attempts. Permissions/deployed engine can deny listings.

## Turn in work deliberately

```sh
canvas-pocket upload-assignment-file 123 456 --file paper.pdf
canvas-pocket submit-file 123 456 789
canvas-pocket submit-text 123 456 --text-file response.txt
canvas-pocket submit-url 123 456 --url-file project-url.txt
canvas-pocket submission-comment 123 456 --message-file question.txt
```

These start as previews; follow [confirmation](safety.md#confirmation). Upload stages a file, not a submission. Submit the returned file ID separately; multiple staged IDs are supported.

Previews check exact assignment, allowed type, publication/lock, account, destination, and content/file metadata. URL input is one absolute HTTP(S) URL read from a file. Plain text-entry/discussion input is escaped to HTML.

Comments are not submissions. Group/graded work may have a shared audience; review destination, content, and course rules. Canvas enforces final membership/acceptance. After uncertainty, check Canvas before repeating.

## Sources

[Assignments](https://developerdocs.instructure.com/services/canvas/resources/assignments), [Submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions), [Modules](https://developerdocs.instructure.com/services/canvas/resources/modules), [New Quizzes](https://developerdocs.instructure.com/services/canvas/resources/new_quizzes).
