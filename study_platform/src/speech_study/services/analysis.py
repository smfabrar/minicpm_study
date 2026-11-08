"""Summaries retain failed, silent and unreviewed attempts in denominators."""

import statistics

from ..artifacts import ArtifactStore
from .studies import StudyService

from ..domain.models import Condition, RunStatus, StudyStatus
from .callers import run_caller


class AnalysisService:
    def __init__(self, studies: StudyService, artifacts: ArtifactStore):
        self.studies = studies
        self.artifacts = artifacts

    def summarize(self, study_id: str) -> dict:
        return self.summarize_details(self.studies.get(study_id))

    def summarize_details(self, details) -> dict:
        groups = {}
        for profile in details.study.caller_profiles:
            groups[tuple(sorted(profile.items()))] = (profile, [])
        for run in details.runs:
            profile = run_caller(run)
            key = tuple(sorted(profile.items()))
            groups.setdefault(key, (profile, []))[1].append(run)
        report = self._conditions(details, details.runs)
        return {"conditions": report,
                "callers": [{"profile": profile, "conditions": self._conditions(details, runs)}
                            for profile, runs in groups.values()],
                "pending": sum(r.status in {RunStatus.QUEUED, RunStatus.RUNNING} for r in details.runs),
                "notes": ["Compare caller groups separately; model, revision, device and precision identify each group.",
                          "B0 and B2 are repeated controls in each comparison set; only B1 uses that set's caller.",
                          "Primary accuracy uses frozen evaluation-split tool-required attempts, including failed, silent and unreviewed attempts.",
                          "A human listening verdict supplies spoken correctness. ASR and model text assist review.",
                          "Latency and memory summaries use frozen evaluation-split attempts only."]}

    @staticmethod
    def _conditions(details, runs):
        report = []
        for condition in Condition:
            attempts = [r for r in runs if r.condition == condition and r.status not in {RunStatus.QUEUED, RunStatus.RUNNING}]
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
        return report
