"""Describe output received after evaluation without inferring spoken correctness."""

from pathlib import Path

from ..audio import read_pcm, write_pcm


def observe_context(trace: dict, output_dir: Path, end_ns: int | None) -> dict:
    events = trace["events"]
    submitted = next((e for e in events if e["name"] == "context.submitted"), None)
    ack = next((e for e in events if e["name"] == "context.evaluated" and submitted
                and e["attributes"]["event_id"] == submitted["attributes"]["event_id"]), None)
    report = {
        "status": "not_submitted" if not submitted else "not_evaluated",
        "evaluated": ack is not None,
        "new_text": "",
        "audio_chunks": 0,
        "audio_duration_ms": 0,
        "output_audio": None,
        "clip_error": None,
        "observation_ms": None,
        "evaluation_latency_ms": None,
        "first_text_after_evaluation_ms": None,
        "spoken_correctness": "requires_listening_review",
        "note": "Output received after evaluation may include buffered speech. New text and audio do not prove the fact was spoken.",
    }
    if ack is None:
        return report
    at = ack["at_ns"]
    report["evaluation_latency_ms"] = (at - submitted["at_ns"]) / 1e6
    report["observation_ms"] = (end_ns - at) / 1e6 if end_ns is not None else None
    text_events = [e for e in events if e["name"] == "native.event" and e["at_ns"] >= at
                   and (end_ns is None or e["at_ns"] <= end_ns)
                   and e["attributes"]["event"].get("type") == "response.output.delta"
                   and e["attributes"]["event"].get("kind") == "text"
                   and e["attributes"]["event"].get("text")]
    report["new_text"] = "".join(e["attributes"]["event"]["text"] for e in text_events)
    report["status"] = "evaluated_with_new_text" if report["new_text"].strip() else "evaluated_no_new_text"
    if text_events:
        report["first_text_after_evaluation_ms"] = (text_events[0]["at_ns"] - at) / 1e6
    audio = [e for e in events if e["name"] == "audio.output_emitted" and e["at_ns"] >= at
             and (end_ns is None or e["at_ns"] <= end_ns)]
    report["audio_chunks"] = len(audio)
    report["audio_duration_ms"] = sum(e["attributes"]["duration_ms"] for e in audio)
    if audio:
        # Chunk events use a one-based count; chunk filenames are zero-based.
        try:
            pcm = b"".join(read_pcm(output_dir / f"speaker_{e['attributes']['chunk'] - 1:04d}.wav",
                                    target_rate=24000) for e in audio)
            write_pcm(output_dir / "after_context.wav", pcm, 24000)
            report["output_audio"] = "after_context.wav"
        except (OSError, ValueError) as exc:
            report["clip_error"] = str(exc)
    return report
