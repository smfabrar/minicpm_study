"""Initial fixture definitions for a new study; no tool execution."""


def default_tools():
    return [
        {"name": "room_lookup", "description": "Find the room for a named seminar or event.", "parameter": "name", "kind": "room", "records": {"robotics seminar": "The robotics seminar is in room B742.", "vision seminar": "The vision seminar is in room C314.", "NLP seminar": "The NLP seminar is in room A205."}, "aliases": {"robotic seminar": "robotics seminar"}, "delay_ms": 0},
        {"name": "document_search", "description": "Search local documents for an explicitly requested topic.", "parameter": "query", "kind": "document", "records": {"Lab access": "The language lab opens at 09:00 and closes at 17:00. Access requires a student card.", "Submission policy": "The project report must be submitted as a PDF through the course portal."}, "delay_ms": 0},
        {"name": "calculator", "description": "Calculate an explicit basic arithmetic expression.", "parameter": "expression", "kind": "calculator", "records": {}, "delay_ms": 0},
    ]
