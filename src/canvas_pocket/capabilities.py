"""Human- and machine-readable map of the supported command surface."""


def describe():
    return {
        'read': [
            'courses', 'doctor', 'me', 'favorites', 'groups', 'group', 'course-groups',
            'inbox', 'conversation (no read-state change)', 'recipients',
            'todo', 'upcoming', 'calendar', 'overview', 'deadlines', 'work',
            'news', 'linked-files', 'assignments', 'assignment',
            'assignment-groups', 'assignment-group', 'submission', 'grades',
            'syllabus', 'modules', 'module-items', 'outline', 'pages', 'page',
            'files', 'my-files', 'file-info', 'folders', 'folder-files',
            'sections', 'announcements', 'discussions', 'topic', 'entries',
            'replies', 'quizzes (metadata only)', 'quiz (metadata only)',
            'new-quizzes (metadata only)', 'new-quiz (metadata only)',
            'rubrics', 'rubric', 'get', 'snapshot-diff (offline)',
            'snapshot-search (offline)',
        ],
        'local_write': [
            'snapshot (private local file)',
            'snapshot-markdown (private local file, offline)',
            'download', 'download-linked (preview unless --yes)',
        ],
        'canvas_write': [
            'post (preview and matching digest required)',
            'inbox-reply/inbox-compose (preview and matching digest required)',
            'submit-url/submit-text/submit-file (preview and matching digest required)',
            'upload-personal/upload-assignment-file (preview and matching digest required; assignment upload does not submit)',
        ],
        'auth': ['login', 'status', 'logout'],
        'format': 'JSON or human-readable brief index',
        'limitations': [
            'No quiz attempts', 'No OAuth browser consent yet',
            'Live uploads and submissions not yet validated',
        ],
    }
