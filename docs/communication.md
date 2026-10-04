# Communication

[Documentation](README.md) · [Safety](safety.md) · [Notifications](account.md#notification-preferences)

## Inbox

```sh
canvas inbox --scope unread --course 123
canvas conversation 456
canvas recipients --search 'Example Name' --course 123
canvas inbox-compose --recipient 789 --subject 'Question' --message-file message.txt
canvas inbox-reply 456 --message-file reply.txt
```

Conversation reads explicitly disable automatic mark-as-read; unsafe GETs are blocked even through expert get. Recipient search is the authorized messageable directory. Numeric user lookup cannot also select course context because Canvas ignores that filter.

Compose targets one verified individual, not a course/group ID; Canvas may reuse an existing private thread. Compose/reply previews bind account, audience, and exact UTF-8 text. Changed participants/message state invalidate [confirmation](safety.md#confirmation).

### Organize your own Inbox

Edit changes selected read/unread/archive/star and confirmed group-conversation subscription fields. Archive preserves messages; read/unread restores an archived thread. Subscription affects your ordering/unread flags, not other participants.

Delete with permanent acknowledgement removes your own copies, not everyone's. No Canvas CLI restore exists; archive to retain messages.

Content-free previews bind account/current state/message revision. New messages invalidate previews. Organization commands send no message; ordinary reads change no read marker.

## Discussions

```sh
canvas thread 123 456 --format brief
canvas entry 123 456 789
canvas post 123 456 --reply-to 789 --message-file reply.txt
```

Discussion/announcement listings, topics, threads, entries/replies, posts, edits, ratings, subscriptions, and markers support explicit group context; course is default. Namespaces are not interchangeable. Publication, locks, permissions, and initial-post restrictions remain enforced.

Thread follows entry and separate reply pagination when embedded ten-reply lists are insufficient. Denied replies are partial. Output can contain classmates' names/posts; keep private. No explicit mark-read write occurs.

Posts escape UTF-8 text to HTML and bind current topic/account/content. Replies also verify the exact visible non-deleted entry.

### Own edits and likes

Entry-edit/delete verify own authorship and current entry/context/account. They never delete the topic/assignment. Changed content/attachment/owner requires fresh confirmation; graded-post changes can affect credit.

Text editing can remove an attachment; remove-attachment explicitly acknowledges loss. Use the native editor to preserve it. Delete requires exact empty HTTP 204.

Topic-ratings shows own cached likes/represented entry IDs, not bodies/other people. Disabled ratings skip cached reads. Cache is eventually consistent; an absent vote is known only for represented entries.

Entry-rate sets/removes your like (1/0), not grades/text. It binds current target revision/topic/rating/account; native grader-only/access rights still apply.

### Read markers and subscriptions

Topic subscribe/unsubscribe changes your notifications. Topic markers cover initial text, not all replies. Entry markers affect one visible entry, including another author's, not content.

Forced-read-state sets a manual override; its explicit negation clears it; omission preserves it. Closed-topic subscription remains subject to access. These are separately confirmed writes; acknowledgement does not prove a person read or completed work.

### Create a discussion prompt

```sh
canvas topic-create 123 --title 'New topic' --message-file prompt.txt --acknowledge-shared-topic
canvas topic-create 123 --context group --title 'Team question' --acknowledge-shared-topic
canvas topic-create 123 --title 'Draft topic' --no-published --acknowledge-shared-topic
```

Creation uses the dynamic `create_discussion_topic` permission reported by the exact course/group with `include[]=permissions`, not an inferred role or the raw context-permissions endpoint. Native `moderate_forum` determines the default: moderators get a draft, other permitted creators a published topic. Explicit `--published` or `--no-published` binds your choice; drafts require moderation permission and are not necessarily private from moderators.

Title is required; omitted body stays native-empty. Supplied UTF-8 plain text is escaped to HTML. The preview binds account, context, creation/moderation rights, complete accessible topic inventory and exact content/publication choice. One POST must produce a new ID and own author, matching independent topic readback and an inventory entry. Own edit/delete rights need not be enabled to create. Stored text/publication mismatches are labeled, not silently repaired.

Only ordinary ungraded non-anonymous course/group topics are supported. No attachments, assignment/group-set links, section overrides or advanced scheduling/options are requested. Canvas defaults/HTML processing remain native; notifications and ordering effects are not proven. An uncertain result never triggers retry, deletion or rollback. Duplicate titles are allowed and do not prove an existing topic was created.

### Duplicate a discussion prompt

```sh
canvas topic-duplicate 123 456 --acknowledge-shared-topic --acknowledge-copy-effects
canvas topic-duplicate 123 456 --context group --acknowledge-shared-topic --acknowledge-copy-effects
```

This invokes native copying, not a complete backup. The prompt, selected options/dates and section associations are copied; replies, attachment associations and participant overrides are not. Embedded file links can still refer to original files. Losing participant overrides can widen the audience. Moderators normally get a draft; other permitted creators are auto-published. Copied dates can affect availability, and a pinned copy shifts other topics. Both acknowledgements are required even for preview.

Dynamic creation permission is required. Course copying additionally requires native instructor eligibility by enrollment date or context `read_as_admin`; moderation alone is insufficient. The preview reports the exact admin flag without guessing instructor eligibility from roles. The endpoint remains authoritative. An explicit `initial_post_required` subscription hold is refused; the reply-visibility flag alone cannot determine the native gate, which also considers observer-associated users. No peer entries are inspected or restrictions bypassed.

Account, exact source, reported audience, context/rights and the complete accessible inventory bind confirmation. One POST must yield a new ID, own author, independent topic/source readback and an inventory entry. Pinned responses are serialized before insertion, so their top-level position is not treated as the stored position: the native position map and fresh accessible positions must agree. Unknown map IDs are counted, not exposed or asserted verified. Copied-field differences and attachment counts are labeled, not silently repaired.

Ordinary ungraded, non-anonymous course/group topics only. Announcements, graded topics and root/child/group-set associations need separate workflows. Readback is not immutable lineage, a perfect-copy guarantee, an atomic lock or proof of hidden ordering, future jobs, notifications or linked-file access. Inspect the new audience before use. An uncertain result never triggers retry, deletion, cleanup or rollback.

### Manage a discussion prompt

```sh
canvas topic-edit 123 456 --title 'Updated topic' --acknowledge-shared-topic
canvas topic-edit 123 456 --message-file prompt.txt --acknowledge-shared-topic
canvas topic-delete 123 456 --acknowledge-shared-topic --acknowledge-topic-removal
```

These are shared prompt changes, not replies or submissions. Course/group context is explicit; native per-topic update/delete permissions, not ownership or guessed enrollment roles, govern access. Readable drafts can be edited when Canvas permits it. Title/body omission preserves that field; text is escaped to HTML. Existing topic attachments are not explicitly removed, unlike entry editing.

Previews bind account, exact topic/content, reported audience, permissions and the complete accessible topic inventory. Prior bodies, private audience records and signed file/feed URLs are omitted. Independent readback distinguishes stored text from HTML normalization/ignored changes and labels other observed field changes. Native notification/module/pacing/blueprint effects are not asserted verified.

Deletion requires additional removal acknowledgement. One native soft DELETE must be acknowledged as deleted, disappear from the paginated active-topic inventory and return exact-ID 404/410. Access denial alone is not deletion proof; no permanent-erasure claim or CLI restore. Uncertain outcomes never retry, roll back or clean up automatically.

Graded topics, announcements, anonymous topics and root/child/group-set associations remain separate, unsupported management workflows. Initial-post protections still govern peer replies; these commands do not inspect them. Preflight is not an atomic lock and concurrent edits can be overwritten.

### Publication, closing and pinning

```sh
canvas topic-publish 123 456 --acknowledge-shared-topic
canvas topic-unpublish 123 456 --acknowledge-shared-topic
canvas topic-close 123 456 --acknowledge-shared-topic
canvas topic-open 123 456 --acknowledge-shared-topic --acknowledge-closing-schedule-removal
canvas topic-pin 123 456 --acknowledge-shared-topic --acknowledge-topic-ordering-change
canvas topic-unpin 123 456 --acknowledge-shared-topic --acknowledge-topic-ordering-change
```

Each verb previews one native boolean change on an ordinary ungraded topic. Exact update permission remains required; moving to draft also requires the reported `can_unpublish` eligibility, and closing requires `can_lock`. Do not substitute ownership or total reply counts for these flags. No peer-post enumeration is performed. A verified state change can legitimately remove future edit permission.

Published is not a promise of immediate availability: existing opening dates, course/module restrictions and future jobs remain native. Close affects replies, not deletion. Reopening a closed topic with `lock_at` clears that closing date and requires separate acknowledgement. Opening an already open topic is a no-op, not cancellation of its future closing schedule.

Pin/unpin requires ordering acknowledgement because moving to the bottom of a native ordering scope can shift other topics. Account, exact prompt/audience/eligibility, scope and complete accessible inventory bind confirmation. One PUT must independently read back the requested state, any acknowledged closing-date removal and a matching inventory entry. Ignored states or unverified outcomes fail without retry/cleanup. Other observed fields and added/removed/changed inventory IDs are labeled, not attributed exclusively to the write; hidden ordering, notifications and future effects are not proven.

### Schedule course discussion dates

```sh
canvas topic-schedule 123 456 --opens-at 2027-10-01T09:00:00-07:00 --closes-at 2027-10-15T23:59:00-07:00 --acknowledge-shared-topic --acknowledge-availability-change
canvas topic-schedule 123 456 --clear-opening --clear-closing --acknowledge-shared-topic --acknowledge-availability-change
```

This sets selected opening/closing dates, not assignment due dates or private reminders. Omitted dates are preserved; clearing is explicit. Supply whole-second RFC 3339 instants with `Z` or an offset. Closing must follow opening, including preserved dates. Course-midnight closing is refused because Canvas rewrites it to end of day; a selected closing instant needs the course's reported IANA time zone. Group, graded, anonymous and root/group-set scheduling require separate workflows.

Availability acknowledgement is required even for preview: native date changes can publish a draft, delay opening, reopen replies or close them immediately. Already-matching instants are no-ops, not publication controls. Account, context/time zone, prompt/audience and complete accessible inventory bind confirmation. One PUT must independently read back every selected instant or explicit clearing; equivalent offsets are accepted, changed instants and partial/ignored writes are not. Observed publication/closed-state changes are labeled, not predicted or attributed exclusively to this write. Future jobs, actual student availability through pacing/modules/overrides and notifications remain unverified. No peer-post reads, retries or rollback.

### Set the shared student to-do date

```sh
canvas topic-todo 123 456 --todo-at 2027-10-01T09:00:00-07:00 --acknowledge-shared-topic --acknowledge-student-todo-change
canvas topic-todo 123 456 --context group --clear-todo --acknowledge-shared-topic --acknowledge-student-todo-change
```

This changes an ungraded discussion's shared student to-do date, not a private planner task, graded due date or opening/closing date. Both acknowledgements are required even for preview. Course and group contexts are supported. Setting a non-null date requires the exact native context `manage_course_content_add` permission as well as topic-update permission. Clearing requires topic update but does not impose the additional add permission that Canvas skips for null values. Ownership, enrollment labels and moderation alone are not substituted for these checks.

Use a whole-second RFC 3339 instant with `Z` or an explicit offset; clearing is explicit and an already-matching date is a no-op. Past and midnight instants are allowed; opening/closing-date ordering and course-midnight rewriting are not invented for to-do dates. Missing native date metadata is unknown, not assumed unset.

Account, exact prompt/audience, context, required permission and complete accessible inventory bind confirmation. One PUT must independently read back the selected instant or clearing and a matching inventory entry. Equivalent offsets are accepted; ignored/shifted dates, stale previews and uncertain outcomes fail without retry, cleanup or rollback. Other observed changes are labeled, not exclusive causal proof. Stored-date verification does not prove student planner/feed visibility, completion, notifications, future jobs or availability. No peer-post, grading, submission or read-marker action occurs. Graded, anonymous, announcement and root/child/group-set topics need separate workflows.

### Filter a course topic by section

```sh
canvas topic-sections 123 456 --section-id 789 --section-id 790 --acknowledge-shared-topic --acknowledge-audience-change
canvas topic-sections 123 456 --all-sections --acknowledge-shared-topic --acknowledge-audience-change
```

This replaces the native course section filter on an ordinary ungraded topic. Repeat `--section-id` for each selected active course section; `--all-sections` disables this filter. Both acknowledgements are required even for preview because access to the prompt and existing replies can widen or narrow. Group contexts do not have course section filters. Graded, anonymous, announcement and root/child/group-set topics remain separate workflows.

Section filtering is **not modern participant-override configuration**. Existing participant overrides are not sent or replaced, and Canvas can report derived legacy section visibilities alongside those overrides. All sections does not prove that everyone can see the topic: participant overrides, dates, modules and other native restrictions still apply. Exact topic update permission is required; the native endpoint also checks visibility of old and new sections. The section inventory is not proof of editing authority, and the different modern `manage_assign_to` permission is not substituted for this API's native checks.

The complete paginated active course section list, exact prompt/audience, account, context and topic inventory bind confirmation. Section names/SIS records, roster identities, prior prompt text and peer replies are not emitted or enumerated. One PUT must acknowledge and independently read back the exact filter state and selected IDs, with a stable section catalog. Ignored/partial writes, stale previews and unreadable outcomes fail without retry, cleanup or rollback. An HTTP error is not proof that section associations stayed unchanged; check Canvas before repeating. Other metadata changes, including derived override metadata, are labeled observations rather than exclusive causal proof. Effective per-student visibility, module progression invalidation, notifications and activity effects are not verified.

The workflow follows the [documented discussion API](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), [course sections API](https://developerdocs.instructure.com/services/canvas/resources/sections) and [native section validation](https://github.com/instructure/canvas-lms/blob/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c/app/controllers/discussion_topics_controller.rb). Tests are synthetic; no live section-filter write has been performed.

### Order all pinned topics

```sh
canvas topic-order 123 789 456 --acknowledge-all-pinned-topics
canvas topic-order 123 789 456 --context group --acknowledge-all-pinned-topics
```

Supply every accessible pinned topic exactly once in the desired order. Unpinned, omitted, duplicate or foreign IDs are refused. This changes the shared pinned list, not personal preferences; graded/section-specific topics may participate without editing their prompts or assignments. Permission on one authored topic does not authorize context ordering: the native temporary-topic update policy requires context `read_forum` and `moderate_forum`.

Account, context, rights and the complete accessible inventory bind the preview. One native POST must acknowledge the exact full order as native ID strings, then independently read back unambiguous positions in that order. Unexpected IDs, ambiguous positions, partial inventories, ignored orders and unverified outcomes fail without retry/rollback. Accessible inventory is not proof that hidden topics do not exist; other observed changes are not exclusively attributed to this write. No pin toggling, peer-post inspection, prompt/assignment edits or notification guarantee.

### Configure replies, likes and default views

```sh
canvas topic-configure 123 456 --sort-order desc --expanded --expanded-locked --acknowledge-shared-topic
canvas topic-configure 123 456 --no-allow-rating --acknowledge-shared-topic
canvas topic-configure 123 456 --require-initial-post --acknowledge-shared-topic --acknowledge-reply-visibility-change
```

These settings affect the shared topic, not your personal reading preferences. Omitted options are preserved; boolean options have explicit positive/negative forms. Use `canvas help topic-configure` for the supported reply/like/sort/expansion choices. `flat` is a native model discussion type. Course/group context is explicit; group updates do not accept `require_initial_post`. Locking expansion requires the effective final state to be expanded, including current values you did not select.

Changing the initial-post requirement needs separate visibility acknowledgement because existing replies can become visible or hidden to other participants. Only the prompt/settings are inspected, never peers' replies. Exact native update permission governs access; ownership and role-name guesses do not substitute for it. Institution-enabled granular permissions or blueprint restrictions can reject or discard options. Their absence is not guessed, and an ignored/partially applied selection fails verification rather than being reported as success.

The existing account/content/audience/inventory-bound pipeline performs one PUT and independently verifies every selected stored value plus the inventory entry. Unrequested metadata/inventory changes remain observations, not exclusive causal proof. No entry rewriting/deletion, read-marker change, automatic retry, cleanup or rollback. Podcasts and modern participant/assignment override configuration remain open.

## Peer reviews

```sh
canvas peer-reviews 123 456 --include-comments --include-users
```

Default scope is reviews of your submission, not reviews owed. Output always states incomplete owed-review coverage. Visible scope adds only native authorized records, not elevation/enumeration.

Comments can repeat or belong to someone other than the assessor. Anonymous/missing assessor identities are not reconstructed; missing IDs omit associations. Assignment visibility/lock/identity, duplicates, and pagination are checked.

No allocation, completion, grading, attempt, or read-state write occurs.

## Activity and announcements

```sh
canvas news --days 30 --format brief
canvas activity --active --format brief
canvas activity --course 123 --type AssessmentRequest
canvas activity-summary
```

News reads posted announcements per course, reporting unavailable courses. JSON includes visible bodies; brief is a title/date index. Window is posting time, not later edits.

Activity paginates own global/course feed before exact-type filtering. Default is metadata/safe links; content opt-in enables selected private bodies. Current discussion access is rechecked before cached prompts/entries; unverified/post-first-restricted content stays withheld. Cached previews may be incomplete/outdated; use source thread/conversation/submission commands.

Empty feeds/counts are not complete assignment/owed-review inventories.

Dismiss hides one own notification; dismiss-all with all acknowledgement hides every stream item, including outside displayed inventory. Previews bind account/site/full revisions without echoing bodies. No source/read marker/grade/submission changes; no Canvas CLI restore.

## Sources

[Conversations](https://developerdocs.instructure.com/services/canvas/resources/conversations), [Recipients](https://developerdocs.instructure.com/services/canvas/resources/search), [Discussions](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), [Peer reviews](https://developerdocs.instructure.com/services/canvas/resources/peer_reviews), [Announcements](https://developerdocs.instructure.com/services/canvas/resources/announcements), [Activity](https://developerdocs.instructure.com/services/canvas/resources/users).

Prompt-management semantics also follow Instructure's [controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_topics_controller.rb), [API serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/discussion_topics.rb), [API reads](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_topics_api_controller.rb), [topic model](https://github.com/instructure/canvas-lms/blob/master/app/models/discussion_topic.rb), [midnight normalization](https://github.com/instructure/canvas-lms/blob/master/gems/canvas_time/lib/canvas_time.rb) and [native list ordering](https://github.com/instructure/canvas-lms/blob/master/gems/acts_as_list/lib/active_record/acts/list.rb).

Creation authorization follows the dynamic permissions in the native [course serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/course_json.rb) and [group serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/group.rb), not a role-name guess.
