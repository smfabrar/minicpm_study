"""Summaries retain failed, silent and unreviewed attempts in denominators."""

import statistics

from ..artifacts import ArtifactStore
from .studies import StudyService

from ..domain.models import Condition, RunStatus, StudyStatus


class AnalysisService:
    def __init__(self, studies: StudyService, artifacts: ArtifactStore):
        self.studies = studies
        self.artifacts = artifacts

    def summarize(self, study_id: str) -> dict:
        return self.summarize_details(self.studies.get(study_id))

    def summarize_details(self, details) -> dict:
        report = []
        for condition in Condition:
            attempts = [r for r in details.runs if r.condition == condition and r.status not in {RunStatus.QUEUED, RunStatus.RUNNING}]
            evaluation = [r for r in attempts if r.study_status == StudyStatus.FROZEN and next((c for c in r.snapshot["cases"] if c["id"] == r.case_id), {}).get("split") == "evaluation"]
            primary = [r for r in evaluation if next((c for c in r.snapshot["cases"] if c["id"] == r.case_id), {}).get("category") != "none"]
            correct = sum(r.review is not None and r.review.verdict == "correct" and r.status == RunStatus.COMPLETE for r in primary)
            latency = [r.result["metrics"]["input_start_to_first_audio_ms"] for r in evaluation if r.result and r.result.get("metrics", {}).get("input_start_to_first_audio_ms") is not None]
            memory = [r.result["metrics"]["memory"]["observed_peak_rss_bytes"] for r in evaluation if r.result and r.result.get("metrics", {}).get("memory", {}).get("observed_peak_rss_bytes") is not None]
            no_tool = [r for r in evaluation if next((c for c in r.snapshot["cases"] if c["id"] == r.case_id), {}).get("category") == "none"]
            unnecessary = sum(bool(r.result and (r.result.get("caller_action") or {}).get("kind") == "call") for r in no_tool)
            report.append({"condition": condition, "attempted": len(attempts), "evaluation_attempts": len(evaluation),
                           "primary_attempts": len(primary), "confirmed_correct": correct,
                           "spoken_accuracy": correct / len(primary) if primary else None,
                           "unreviewed": sum(r.review is None or r.review.verdict == "unreviewed" for r in primary),
                           "failed": sum(r.status in {RunStatus.FAILED, RunStatus.INTERRUPTED} for r in attempts),
                           "silent": sum(r.status == RunStatus.SILENT for r in attempts),
                           "median_first_audio_ms": statistics.median(latency) if latency else None,
                           "peak_observed_rss_bytes": max(memory) if memory else None,
                           "no_tool_attempts": len(no_tool), "unnecessary_calls": unnecessary})
        return {"conditions": report, "pending": sum(r.status in {RunStatus.QUEUED, RunStatus.RUNNING} for r in details.runs),
                "notes": ["Primary accuracy uses frozen evaluation-split tool-required attempts. Silent and failed attempts remain in its denominator.", "Unreviewed attempts are shown explicitly; accuracy is confirmed correct / attempted.", "ASR and model text assist review; a human listening verdict supplies spoken correctness.", "Latency and memory summaries use frozen evaluation-split attempts only.", "Synthesized and uploaded audio origins are retained per case. Timing comparisons require matching configurations."]}
