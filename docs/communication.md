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

### Configure replies, likes and default views

```sh
canvas topic-configure 123 456 --sort-order desc --expanded --expanded-locked --acknowledge-shared-topic
canvas topic-configure 123 456 --no-allow-rating --acknowledge-shared-topic
canvas topic-configure 123 456 --require-initial-post --acknowledge-shared-topic --acknowledge-reply-visibility-change
```

These settings affect the shared topic, not your personal reading preferences. Omitted options are preserved; boolean options have explicit positive/negative forms. Use `canvas help topic-configure` for the supported reply/like/sort/expansion choices. `flat` is a native model discussion type. Course/group context is explicit; group updates do not accept `require_initial_post`. Locking expansion requires the effective final state to be expanded, including current values you did not select.

Changing the initial-post requirement needs separate visibility acknowledgement because existing replies can become visible or hidden to other participants. Only the prompt/settings are inspected, never peers' replies. Exact native update permission governs access; ownership and role-name guesses do not substitute for it. Institution-enabled granular permissions or blueprint restrictions can reject or discard options. Their absence is not guessed, and an ignored/partially applied selection fails verification rather than being reported as success.

The existing account/content/audience/inventory-bound pipeline performs one PUT and independently verifies every selected stored value plus the inventory entry. Unrequested metadata/inventory changes remain observations, not exclusive causal proof. No entry rewriting/deletion, read-marker change, automatic retry, cleanup or rollback. Advanced dates, podcasts and audience/assignment configuration remain open.

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

Prompt-management semantics also follow Instructure's [controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_topics_controller.rb), [API serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/discussion_topics.rb), [API reads](https://github.com/instructure/canvas-lms/blob/master/app/controllers/discussion_topics_api_controller.rb) and [topic model](https://github.com/instructure/canvas-lms/blob/master/app/models/discussion_topic.rb).

Creation authorization follows the dynamic permissions in the native [course serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/course_json.rb) and [group serializer](https://github.com/instructure/canvas-lms/blob/master/lib/api/v1/group.rb), not a role-name guess.
