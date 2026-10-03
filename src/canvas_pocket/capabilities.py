"""Human- and machine-readable map of the supported command surface."""


def describe():
    return {
        'read': [
            'courses', 'doctor', 'find', 'me', 'favorites', 'groups', 'group', 'course-groups',
            'nicknames', 'nickname', 'colors', 'color',
            'inbox', 'conversation (no read-state change)', 'recipients',
            'todo', 'upcoming', 'calendar', 'event', 'planner', 'planner-notes', 'planner-note',
            'planner-overrides', 'planner-override', 'module-progress', 'overview', 'deadlines', 'work', 'agenda',
            'exports', 'export-status',
            'news', 'linked-files', 'assignments', 'assignment',
            'assignment-groups', 'assignment-group', 'submission', 'grades', 'peer-reviews',
            'syllabus', 'tabs', 'front-page', 'modules', 'module-items', 'outline', 'pages', 'page',
            'files', 'my-files', 'file-info', 'folders', 'my-folders', 'my-root', 'folder', 'folder-files', 'folder-folders',
            'sections', 'announcements', 'discussions', 'topic', 'thread', 'entries', 'entry',
            'replies', 'quizzes (metadata only)', 'quiz (metadata only)',
            'new-quizzes (metadata only)', 'new-quiz (metadata only)',
            'rubrics', 'rubric', 'get', 'snapshot-diff (offline)',
            'snapshot-search (offline)',
        ],
        'local_write': [
            'snapshot (private local file)',
            'sync (private local snapshot and change summary)',
            'snapshot-markdown (private local file, offline)',
            'download', 'download-linked (preview unless --yes)', 'export-download',
        ],
        'canvas_write': [
            'favorite-add/favorite-remove/favorites-reset (own course/group favorites; account-bound preview, displayed-default warning and matching digest required)',
            'nickname-set/nickname-clear/nicknames-reset/color-set (own display preferences; account-bound preview and matching digest required, no shared course renaming)',
            'event-create/event-edit/event-delete (personal calendar only; account-bound preview and matching digest required)',
            'task-create/task-edit/task-delete (personal planner notes; account-bound preview and matching digest required)',
            'planner-override-create/planner-override-edit/planner-override-delete (planner completion/dismissal; account-bound preview, explicit module-progress acknowledgement for course content)',
            'post (preview and matching digest required)',
            'entry-edit/entry-delete (own entry only; account-bound preview, matching digest and attachment-loss acknowledgement)',
            'topic-subscribe/topic-unsubscribe/topic-mark-read/topic-mark-unread/entry-mark-read/entry-mark-unread (only own subscription/read markers; account-bound preview and matching digest required)',
            'inbox-reply/inbox-compose (preview and matching digest required)',
            'inbox-edit/inbox-delete (own read/archive/star/subscription state or own-view removal; account-bound preview, matching digest and permanent-deletion acknowledgement)',
            'submit-url/submit-text/submit-file (preview and matching digest required)',
            'submission-comment (own submission only; account-bound preview and matching digest required)',
            'export-create (asynchronous course export; account-bound preview and matching digest required)',
            'my-file-edit/my-file-copy/my-file-delete/my-folder-create/my-folder-edit/my-folder-delete (personal file organization; account-bound preview, no overwrite, permanent acknowledgement for file deletion, empty folders only)',
            'upload-personal/upload-assignment-file (preview and matching digest required; assignment upload does not submit)',
        ],
        'auth': ['login', 'status', 'logout'],
        'format': 'JSON or human-readable brief index',
        'limitations': [
            'No quiz attempts', 'No OAuth browser consent yet',
            'Live uploads and submissions not yet validated',
        ],
    }
