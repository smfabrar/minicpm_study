"""Editable starter tool definitions; execution stays in the pipeline."""

import json


DEFAULT_FILE_INDEX = [
    '/projects/orion/finance/budget.xlsx',
    '/archive/team-notes/meeting-notes.txt',
    '/research/drafts/project-report.pdf',
]


def default_tools():
    return [
        {"name": "room_lookup", "description": "Find the room for a named seminar or event.", "parameter": "name", "kind": "room", "records": {"robotics seminar": "The robotics seminar is in room B742.", "vision seminar": "The vision seminar is in room C314.", "NLP seminar": "The NLP seminar is in room A205."}, "aliases": {"robotic seminar": "robotics seminar"}, "delay_ms": 0},
        {
            "name": "document_search", "description": "Locate a file by filename and return its folder and full path from a configured file index. Use when the user asks where a file is saved or which folder contains it. Results distinguish exact matches, approximate candidates and no file found. Does not search document contents. Multiple matches return multiple locations.",
            "parameter": "filename", "kind": "python", "records": {},
            "parameters": {"type": "object", "properties": {"filename": {"type": "string", "minLength": 1, "maxLength": 240, "description": "The filename as requested by the user, including its extension when spoken. Normalize spoken punctuation such as dot PDF to .pdf. Do not invent an omitted extension; the tool can return approximate filename matches."}}, "required": ["filename"], "additionalProperties": False},
            "python_code": "from tool_pipeline.file_index import FileIndex\n\nFILES = " + json.dumps(DEFAULT_FILE_INDEX, indent=4) + "\n\ndef execute(arguments):\n    return FileIndex(FILES).search(arguments['filename'])\n",
            "timeout_seconds": 5, "ground_arguments": False,
        },
        {
            "name": "server_datetime", "description": "Get today's date and the current time when the user asks what time or date it is. Reads the server clock and returns its timezone and UTC. Do not assume the user's local timezone.",
            "parameter": "query", "kind": "python", "records": {},
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "python_code": "from tool_pipeline.live_tools import server_datetime_result\n\ndef execute(arguments):\n    return server_datetime_result()\n",
            "timeout_seconds": 5, "ground_arguments": False,
        },
        {
            "name": "web_search", "description": "Search the web for current or recent information, such as the current prime minister, recent appointments or news. Returns source excerpts, not a verified answer.",
            "parameter": "query", "kind": "python", "records": {},
            "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 240, "description": "A search query based on the user's request"}}, "required": ["query"], "additionalProperties": False},
            "python_code": "from tool_pipeline.live_tools import ExaSearch\n\ndef execute(arguments):\n    return ExaSearch().search(arguments['query'])\n",
            "timeout_seconds": 15, "ground_arguments": False,
        },
    ]
