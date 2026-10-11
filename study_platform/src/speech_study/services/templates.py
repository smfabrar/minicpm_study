"""Proposal-sized question templates; evaluation audio remains user-prepared."""

from .studies import StudyService


def add_proposal_cases(service: StudyService, study_id: str) -> int:
    detail = service.get(study_id)
    if detail.cases:
        raise ValueError("Apply the template to an empty study")
    events = [("robotics seminar", "B742"), ("vision seminar", "C314"), ("NLP seminar", "A205")]
    prompts = ["Where is the {}?", "Which room hosts the {}?", "Tell me the room for the {}.", "Can you look up the location of the {}?"]
    cases = []
    for event, room in events:
        for prompt in prompts:
            cases.append({"question": prompt.format(event), "category": "room", "expected_answer": room, "oracle_result": f"The {event} is in room {room}.", "expected_tool": "room_lookup", "expected_arguments": {"name": event}})
    for a, b in [(17, 23), (8, 9), (12, 7), (19, 4), (6, 14), (21, 5), (13, 11), (16, 3), (7, 18), (9, 15), (24, 4), (11, 12)]:
        cases.append({"question": f"What is {a} times {b}?", "category": "calculator", "expected_answer": str(a * b), "oracle_result": f"{a} * {b} = {a * b}.", "expected_tool": "calculator", "expected_arguments": {"expression": f"{a} times {b}"}})
    for prefix in ["Search local documents for", "Please search the local documents for", "Find local documents about", "Can you search local documents for", "Look in local documents for", "Search the documents for"]:
        for topic, expected, fact in [("lab access", "student card", "The language lab opens at 09:00 and closes at 17:00. Access requires a student card."), ("submission policy", "PDF", "The project report must be submitted as a PDF through the course portal.")]:
            cases.append({"question": f"{prefix} {topic}.", "category": "document", "expected_answer": expected, "oracle_result": fact, "expected_tool": "document_search", "expected_arguments": {"query": topic}})
    for question in ["Hello, how are you?", "Thank you for helping.", "Tell me a short joke.", "What does curiosity mean?", "Good morning.", "How can I introduce myself?", "Explain what a conversation is.", "Say something encouraging.", "What is a metaphor?", "Can you say hello?", "Tell me a short story.", "Goodbye for now."]:
        cases.append({"question": question, "category": "none", "notes": "Review for a relevant conversational response and unnecessary tool calls."})
    for case in cases:
        service.save_case(study_id, {**case, "split": "evaluation"})
    return len(cases)
