# Planning

[Documentation](README.md) · [Coursework](coursework.md) · [Safety](safety.md)

## Read planner/calendar

```sh
canvas planner --start 2026-10-01 --end 2026-10-14 --format brief
canvas planner-notes --course 123 --personal
canvas calendar --active --personal --start 2026-10-01 --end 2026-10-14
```

Own planner paginates today through thirteen days later by default. Course/group/date/native completeness/activity filters complement assignments/instructions, not a complete coursework guarantee. Single note/override reads do not change state; personal includes unassociated notes when course-filtering.

Calendar defaults to own personal context; active/course/group selection is explicit. Native maximum is ten contexts; overflow fails, not silent omission. Undated is undated-only; all includes dated/undated. Neither combines with an ignored date window. Assignment calendar entries use type assignment.

## Personal tasks

```sh
canvas task-create --title 'Read chapter' --date 2026-10-05 --course 123
canvas task-edit 789 --date 2026-10-06
canvas task-delete 789
```

Own planner-note mutations are not assignment edits. [Confirmation](safety.md#confirmation) binds account/site/selected changes/current destination. Changed state invalidates previews.

Edits send selected fields; UTF-8 details-file includes empty to clear; clear-course removes association. Linked tasks cannot change course. Delete cannot combine with edit.

## Personal calendar events

```sh
canvas event-create --title 'Study' --start 2026-10-05T19:00:00-07:00 --end 2026-10-05T20:00:00-07:00
canvas event-create --title 'Read' --date 2026-10-05 --timezone America/Los_Angeles
canvas event-edit 789 --title 'Revised study block'
canvas event-delete 789 --reason 'Schedule changed'
```

Create is personal-only. Edit/delete verify exact own-calendar association and refuse course/group/section/appointment/deleted/hidden/locked events. Recurring edits target one instance, never a series. Scheduler reservations use the separate workflow below.

Timed inputs require seconds/offsets, both start/end, and end later than start. Optional IANA zone verifies offsets for those dates. All-day date+zone handles DST and rejects skipped/ambiguous midnights.

Details are escaped UTF-8. Empty details/location/address clears, omission preserves. Uncertain writes never retry.

## Scheduler appointments

```sh
canvas appointment-groups --course 123 --format brief
canvas appointment-group 456 --format brief
canvas appointment-reserve 456 789 --comments-file question.txt
canvas appointment-cancel 456 987 --reason 'Schedule changed'
```

Discover native Canvas Scheduler groups with full pagination, current slots, reported capacity, and own individual reservation IDs. Past-group and organizer-description reads are opt-ins. Other participants, reservation comments, and group-booking ownership are not exposed. This does not cover UCR advising, Zoom, or external scheduling systems.

Reserve/cancel use fresh [confirmation](safety.md#confirmation) for an exact own individual booking. Reserve requires the own-reservable inventory, never sends another participant or cancels existing bookings, and refuses reported full/already-reserved/limit-met slots. Cancellation targets the own reservation ID, never its parent slot. Group bookings and appointment administration remain separate surfaces.

Comments/reasons can reach the organizer and native notifications may be sent. Comments are bounded UTF-8 from a file. Preflight is not atomic; availability/authorization can change. A separate read verifies own identity, relation, times/comments for booking, or deleted state for cancellation. Failed/mismatched read-back is uncertainty, not success or a retry. No real booking has been live-tested.

## Planner checkboxes

```sh
canvas planner-override-create planner_note 789 --complete
canvas planner-override-create assignment 456 --complete --allow-module-progress
canvas planner-override-edit 123 --dismiss
canvas planner-override-delete 123
```

Create identifies an exact type/ID from the fully paginated own feed; use its reported plannable type/ID and date bounds if needed. Supported types include notes/events/assignments/discussions/announcements/pages/quiz metadata, never questions/attempts. Existing overrides are not duplicated.

Canvas may normalize linked assignment objects; returned associations must match. Override reads verify own ownership.

Edit preserves the other checkbox in outgoing body because native Canvas resets omitted booleans. Explicit complete/dismiss negations are supported. Delete removes override only, not underlying task/assignment, and does not undo recorded module progress.

Course-content changes require allow-module-progress in preview/execution: native Canvas can sync mark-done requirements even on dismissal. Personal notes/events do not. A checkmark is not submission/grade; dismissal is not access.

## Sources

[Planner](https://developerdocs.instructure.com/services/canvas/resources/planner), [Calendar](https://developerdocs.instructure.com/services/canvas/resources/calendar_events), [Appointment groups](https://developerdocs.instructure.com/services/canvas/resources/appointment_groups), [Native reservation projection](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/calendar_event.rb), [Native module side effects](https://github.com/instructure/canvas-lms/blob/master/app/controllers/planner_overrides_controller.rb).
