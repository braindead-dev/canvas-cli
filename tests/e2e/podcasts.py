"""Independent native flag filtering/coupling; never imports CLI validators."""


def apply(row, body, *, group=False, moderator=True, edit_options=True):
    selected = {key: body[key] for key in ('podcast_enabled', 'podcast_has_student_posts') if key in body}
    if group:
        selected.pop('podcast_has_student_posts', None)
    if not selected or moderator is not True or not group and not edit_options:
        return False
    if selected.get('podcast_has_student_posts') is True:
        selected['podcast_enabled'] = True
    if 'podcast_has_student_posts' in selected:
        row['podcast_has_student_posts'] = selected['podcast_has_student_posts']
    if 'podcast_enabled' in selected:
        code = 'group_' if group else 'enrollment_'
        row['podcast_url'] = (f"/feeds/topics/{row['id']}/{code}synthetic-private-feed.rss"
                              if selected['podcast_enabled'] else None)
    return True
