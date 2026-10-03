# Communication

[Documentation](README.md) · [Safety](safety.md) · [Notifications](account.md#notification-preferences)

## Inbox

```sh
canvas-cli inbox --scope unread --course 123
canvas-cli conversation 456
canvas-cli recipients --search 'Example Name' --course 123
canvas-cli inbox-compose --recipient 789 --subject 'Question' --message-file message.txt
canvas-cli inbox-reply 456 --message-file reply.txt
```

Conversation reads explicitly disable automatic mark-as-read; unsafe GETs are blocked even through expert get. Recipient search is the authorized messageable directory. Numeric user lookup cannot also select course context because Canvas ignores that filter.

Compose targets one verified individual, not a course/group ID; Canvas may reuse an existing private thread. Compose/reply previews bind account, audience, and exact UTF-8 text. Changed participants/message state invalidate [confirmation](safety.md#confirmation).

### Organize your own Inbox

Edit changes selected read/unread/archive/star and confirmed group-conversation subscription fields. Archive preserves messages; read/unread restores an archived thread. Subscription affects your ordering/unread flags, not other participants.

Delete with permanent acknowledgement removes your own copies, not everyone's. No Canvas CLI restore exists; archive to retain messages.

Content-free previews bind account/current state/message revision. New messages invalidate previews. Organization commands send no message; ordinary reads change no read marker.

## Discussions

```sh
canvas-cli thread 123 456 --format brief
canvas-cli entry 123 456 789
canvas-cli post 123 456 --reply-to 789 --message-file reply.txt
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

## Peer reviews

```sh
canvas-cli peer-reviews 123 456 --include-comments --include-users
```

Default scope is reviews of your submission, not reviews owed. Output always states incomplete owed-review coverage. Visible scope adds only native authorized records, not elevation/enumeration.

Comments can repeat or belong to someone other than the assessor. Anonymous/missing assessor identities are not reconstructed; missing IDs omit associations. Assignment visibility/lock/identity, duplicates, and pagination are checked.

No allocation, completion, grading, attempt, or read-state write occurs.

## Activity and announcements

```sh
canvas-cli news --days 30 --format brief
canvas-cli activity --active --format brief
canvas-cli activity --course 123 --type AssessmentRequest
canvas-cli activity-summary
```

News reads posted announcements per course, reporting unavailable courses. JSON includes visible bodies; brief is a title/date index. Window is posting time, not later edits.

Activity paginates own global/course feed before exact-type filtering. Default is metadata/safe links; content opt-in enables selected private bodies. Current discussion access is rechecked before cached prompts/entries; unverified/post-first-restricted content stays withheld. Cached previews may be incomplete/outdated; use source thread/conversation/submission commands.

Empty feeds/counts are not complete assignment/owed-review inventories.

Dismiss hides one own notification; dismiss-all with all acknowledgement hides every stream item, including outside displayed inventory. Previews bind account/site/full revisions without echoing bodies. No source/read marker/grade/submission changes; no Canvas CLI restore.

## Sources

[Conversations](https://developerdocs.instructure.com/services/canvas/resources/conversations), [Recipients](https://developerdocs.instructure.com/services/canvas/resources/search), [Discussions](https://developerdocs.instructure.com/services/canvas/resources/discussion_topics), [Peer reviews](https://developerdocs.instructure.com/services/canvas/resources/peer_reviews), [Announcements](https://developerdocs.instructure.com/services/canvas/resources/announcements), [Activity](https://developerdocs.instructure.com/services/canvas/resources/users).
