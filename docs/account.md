# Account and access

[Documentation](README.md) · [Safety](safety.md)

## Own profile

```sh
canvas profile --format brief
canvas profile-set --timezone America/Los_Angeles
canvas profile-set --short-name 'Example Name' --acknowledge-shared-profile
```

Profile whitelists own names/title/pronunciation/pronouns/time zone/locale. Bio/email are opt-ins. Feed secrets/login/SIS/LTI/avatar/services/unknown fields are omitted; expert me/get are raw alternatives, not this projection.

Selected names/text are shared with peers/graders and require acknowledgement; time-zone-only does not. Biography is bounded UTF-8 from a file; empty clears it. Optional text can clear, names cannot. Local limits are 255 single-line characters and 10000 biography characters/40000 bytes.

Fresh previews bind account/site/full profile revision/selected content without echoing unselected bio; files are re-read and SIS override disabled. Native features/permissions/pronoun choices/SIS can ignore/refuse edits; names can derive related names. Time zone affects display, not deadlines.

Update requires own-ID acknowledgement plus a separate GET verifying selected fields. Partial/normalized-different/unavailable readback is uncertainty, not false success/retry. Not an atomic lock; email/login/avatar/locale/status/session edits are excluded.

## Dashboard preferences

| Commands | Behavior |
| --- | --- |
| Favorites add/remove/reset | Own course/group stars, not enrollment |
| Nickname set/clear/reset | Own aliases, not shared course names |
| Color set | Saved custom RGB, not a guessed default |
| Settings set | Exact reported interface booleans, no mobile/unknown keys |
| Dashboard position/order | Merge selected positions, not visibility |

All edits use [confirmation](safety.md#confirmation).

Favorites can be native defaults. First custom selection may replace defaults; removal with no custom stars may save remaining defaults; last removal/reset can restore defaults. Reset clears all custom favorites of that type, not listed IDs. Acknowledged default removal can be a no-op.

Nicknames must be nonempty, shorter than 60 characters, and control-free. Clear restores actual name; reset clears all own aliases; absent alias is not a false removal.

Colors use three/six hex digits; unset is null, not default. User context is own-only; no invented color-clear API.

Settings accept distinct exact reported KEY=true/false pairs. Feature-gated settings may not affect UI. Manual-mark-as-read controls future browser behavior, not existing markers.

Positions are -1000 through 1000; order assigns 0,1,2... Unselected values remain/ties can be ambiguous. Own-user contexts only.

## Notification preferences

```sh
canvas channels --format brief
canvas notification-preferences 123 --category announcement
canvas notification-preferences-set 123 --set new_announcement=immediately
canvas notification-category-set 123 --category announcement --frequency daily
```

Own channel addresses are opt-in for email/SMS, never push/provider tokens or bounce summaries. State is not delivery proof. Contact management is separate below.

Native reads validate exact notification/category keys and reject absent/malformed/duplicate inventories. GETs can persist native default policies without Canvas CLI selecting new frequencies.

Writes send exact selected keys with immediately/daily/weekly/never, through one account/channel/current-state/digest-bound batch. Addresses are hashed, not echoed; other settings untouched.

Category convenience expands only currently reported keys, listing keys/count in preview. Added/removed/recategorized members require fresh confirmation. Future/unreported keys are not affected; no broad native category write.

Failure can partially apply: check Canvas before repeating, no retry/body logging. Course overrides/institution settings can affect delivery; disabling email may hide alerts. No Inbox/enrollment mutation.

## Contact methods

```sh
canvas channel-create --type email --address-file contact.txt --acknowledge-contact-message
canvas channel-delete 123 --acknowledge-contact-removal
```

Creation adds or reactivates an own email/SMS contact; it is not a confirmation resend. The UTF-8 file contains one trimmed line, with one optional LF/CRLF terminator, at most 1024 characters/4096 bytes. Native validation, institution limits and SMS availability still apply. Push registration requires a separate provider/developer-key workflow.

Native confirmation stays enabled, without login creation or confirmation bypass. The selected contact appears in the preview because you must check its destination; results omit addresses. Complete the native confirmation message yourself. Reported active state does not prove delivery.

Deletion retires one exact owned channel ID, including primary/last contacts or a whole push channel. Acknowledgement covers lost alerts, possible primary/recovery-email changes and integration effects. A whole push-channel deletion can affect all its devices; it is not individual token revocation. Managed contacts and OTP-linked SMS may be refused by Canvas.

Both workflows use [confirmation](safety.md#confirmation), binding the account and full owned inventory with addresses hashed. A separate fully paginated inventory verifies the exact contact/state or retirement acknowledgement plus absence. No primary-email/login/integration verification or atomic lock is claimed. Ambiguous acknowledgements, denied/truncated readback or account changes are uncertainty, never a retry. No real contact mutation has been live-tested.

Native behavior is checked against the [contact controller](https://github.com/instructure/canvas-lms/blob/master/app/controllers/communication_channels_controller.rb) and [retirement/OTP model](https://github.com/instructure/canvas-lms/blob/master/app/models/communication_channel.rb).

## Rosters, groups, permissions

```sh
canvas course-users 123 --enrollment-type teacher --include-enrollments
canvas group-users 789 --exclude-inactive
canvas permissions 123 --permission read_roster
canvas category-groups 123 456
canvas group-membership 789
```

Rosters are fully paginated authorized/filter coverage, not a census. Section restrictions can omit people. Names/IDs are metadata-first, email opt-in if native returned. Role/state/section associations are user/course-verified, never grades/SIS/login/bio/avatar/analytics. Native member counts/capacity differ from visible counts; denial/truncation fails.

Permission queries return explicit requested booleans, not reasons/future guarantees. Missing/nonboolean fails; false can mean unsupported/feature-disabled. No grant occurs.

Group sets/categories/groups verify exact course/category scope; reported signup/deadline/limit/multiple-membership settings are not eligibility inference. Default is collaborative, other native filters explicit. No admin-export bypass of denials; member/leader/SIS/progress associations omitted.

Own membership reports accepted/invited/requested records only. No active record does not establish no historical deleted/rejected membership; pending is not accepted.

Join/leave are own-only previewed writes for native student-organized/community roles with explicit native permission. Project switches, unknown/concluded/differentiation groups, invitation-only acceptance, and moderation are excluded. Project switching can remove another membership/recompute submissions, requiring a separate workflow.

Join reports actual returned native state, not presumed acceptance; existing accepted/pending joins fail. Leave can remove access/cancel pending state and trigger notifications. Preflight is not atomic/independent readback; verify ambiguity before repeating.

## Own Canvas enrollments

Inventory preserves own separate sections/roles through full pagination. Native repeated type/state/numeric term filters are supported; course IDs filter locally after pagination. Native default normally active/invited, not history. No grades/SIS/other-user/observer/analytics fields.

Accept/reject require acknowledge-canvas-enrollment plus fresh confirmation for exact pending own invitations. Course/user/enrollment IDs are checked; active/foreign/missing/rejected and admin allocation/role edits are refused.

Accept changes access; reject can hide work/require a new invite. Native self-enrollment restrictions apply. Preflight is not atomic: native accept can revive a concurrently rejected invitation. Acknowledgement is not independent readback.

**Canvas membership is not university registration, credits, registrar drops, waitlists, or tuition-waiver eligibility.**

## Sources

[Users](https://developerdocs.instructure.com/services/canvas/resources/users), [Favorites](https://developerdocs.instructure.com/services/canvas/resources/favorites), [Channels](https://developerdocs.instructure.com/services/canvas/resources/communication_channels), [Notifications](https://developerdocs.instructure.com/services/canvas/resources/notification_preferences), [Groups](https://developerdocs.instructure.com/services/canvas/resources/groups), [Group categories](https://developerdocs.instructure.com/services/canvas/resources/group_categories), [Enrollments](https://developerdocs.instructure.com/services/canvas/resources/enrollments), [Native invite behavior](https://github.com/instructure/canvas-lms/blob/master/app/controllers/enrollments_api_controller.rb).
