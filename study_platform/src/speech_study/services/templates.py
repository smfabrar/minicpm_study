"""Proposal-sized question templates; evaluation audio remains user-prepared."""

from .studies import StudyService
from .default_tools import DEFAULT_FILE_INDEX
from pathlib import PurePosixPath


def add_proposal_cases(service: StudyService, study_id: str) -> int:
    detail = service.get(study_id)
    if detail.cases:
        raise ValueError("Apply the template to an empty study")
    events = [("robotics seminar", "B742"), ("vision seminar", "C314"), ("NLP seminar", "A205")]
    prompts = ["What room is the {} in?", "Do you know where the {} is?",
               "I'm going to the {}. Which room should I head to?", "Where do I need to go for the {}?"]
    cases = []
    for event, room in events:
        for prompt in prompts:
            cases.append({"question": prompt.format(event), "category": "room", "oracle_result": f"The {event} is in room {room}.", "expected_tool": "room_lookup", "expected_arguments": {"name": event}})
    for question in ["What time is it right now?", "Could you check the time for me?",
                     "What's today's date?", "Can you remind me what date it is?",
                     "What date and time is it?", "I've lost track of time. What time is it now?"]:
        cases.append({"question": question, "category": "datetime", "oracle_mode": "server_clock",
                      "expected_tool": "server_datetime", "expected_arguments": {},
                      "notes": "Score against the recorded clock evidence and its stated timezone; do not assume the speaker's local timezone. B2 reads a fresh server clock after its configured delay."})
    for question in ["Who's Sweden's prime minister now?",
                     "What's the latest stable version of Python?",
                     "Who won the latest Nobel Prize in Chemistry?",
                     "Who won the most recent UEFA Champions League final?",
                     "Which movie won Best Picture at the latest Academy Awards?",
                     "What's the European Central Bank's deposit rate right now?"]:
        cases.append({"question": question, "category": "web", "expected_tool": "web_search",
                      "notes": "Manually review the spoken answer against authoritative sources current at run time. Record source URLs and verification dates. Enter a verified B2 oracle before freezing; leave the expected spoken answer blank. Search queries may paraphrase the question; review their meaning, not exact text."})
    file_prompts = ["Where did I save {}?", "Which folder is {} in?",
                    "Can you find {} for me?", "I can't find {}. Where is it?"]
    for indexed_path in DEFAULT_FILE_INDEX:
        path = PurePosixPath(indexed_path)
        fact = f"File {path.name} is in folder {path.parent}. Full path: {indexed_path}."
        for prompt in file_prompts:
            cases.append({"question": prompt.format(path.name), "category": "document",
                          "oracle_result": fact, "expected_tool": "document_search",
                          "expected_arguments": {"filename": path.name},
                          "notes": "Locate the filename in the configured virtual file index. Review the spoken folder/path; no document contents or real filesystem scan are involved."})
    for question in ["Hey, how's it going?", "Thanks, that helps.", "Tell me a quick joke.",
                     "What does it mean to be curious?", "Good morning!", "How should I introduce myself to someone new?",
                     "What makes a good conversation?", "I'm feeling a bit discouraged. Can you say something encouraging?",
                     "What's a metaphor?", "Can you say hello?", "Tell me a short story.", "That's all for now. Bye!"]:
        cases.append({"question": question, "category": "none", "notes": "Review for a relevant conversational response and unnecessary tool calls."})
    for case in cases:
        service.save_case(study_id, {**case, "split": "evaluation"})
    return len(cases)
