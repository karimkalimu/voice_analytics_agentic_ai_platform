import json
from unittest.mock import patch

from pydantic import ValidationError

from app import aggregate_analysis, database
from app.main import app
from app.models import AggregateJobRequest
from support import WorkspaceCase, model_response


class AggregateJobTests(WorkspaceCase):
    def synthesis_response(self, summary="The recordings discuss software and gardening."):
        return model_response(json.dumps({
            "overall_summary": summary,
            "taxonomy": {
                "professional_topics": ["software"],
                "personal_topics": ["gardening"],
                "upcoming_events": [],
            },
        }))

    def group_response(self, summary):
        return model_response(json.dumps({"summary": summary}))

    def user_response(self, summary, professional=None, personal=None, upcoming=None):
        return model_response(json.dumps({
            "summary": summary,
            "taxonomy": {
                "professional_topics": professional or [],
                "personal_topics": personal or [],
                "upcoming_events": upcoming or [],
            },
        }))

    def run_job(self, body):
        request = AggregateJobRequest.model_validate(body)
        job = aggregate_analysis.queue_aggregate_job(request)
        aggregate_analysis.run_aggregate_job(job["id"])
        return database.get_aggregate_job(job["id"])

    def test_user_grouping_isolates_two_users(self):
        first = self.make_file(upload_id="userA1")
        second = self.make_file(upload_id="userA2")
        third = self.make_file(user_id="user-b", upload_id="userB1")
        self.update_row(first, summary="Alpha account discussed backend APIs.")
        self.update_row(second, summary="Alpha account discussed deployment.")
        self.update_row(third, summary="Beta account discussed gardening.",
                        taxonomy=json.dumps({"professional_topics": [],
                                             "personal_topics": ["gardening"], "upcoming_events": []}))
        payloads = []

        def complete(tier, messages, response_format):
            self.assertEqual(tier, "medium")
            self.assertEqual(response_format["json_schema"]["name"], "aggregate_user_summary")
            payload = json.loads(messages[1]["content"])
            payloads.append(payload)
            serialized = json.dumps(payload)
            self.assertFalse("Alpha account" in serialized and "Beta account" in serialized)
            if "Alpha account" in serialized:
                return self.user_response("Alpha summary.", professional=["software"])
            return self.user_response("Beta summary.", personal=["gardening"])

        with patch.object(aggregate_analysis, "complete", side_effect=complete):
            job = self.run_job({"group_by": "user"})
        result = json.loads(job["result_json"])
        self.assertEqual(job["status"], "completed")
        self.assertIsNone(job["user_id"])
        self.assertEqual(result["file_count"], 3)
        self.assertEqual(set(result), {"file_count", "total_duration_sec", "overall_summary",
                                      "group_by", "groups"})
        self.assertEqual(result["groups"], [
            {"user_id": "user-a", "file_count": 2, "total_duration_sec": 4.0,
             "summary": "Alpha summary.", "professional_topics": ["software"],
             "personal_topics": [], "upcoming_events": []},
            {"user_id": "user-b", "file_count": 1, "total_duration_sec": 2.0,
             "summary": "Beta summary.", "professional_topics": [],
             "personal_topics": ["gardening"], "upcoming_events": []},
        ])
        self.assertEqual(len(payloads), 2)

    def test_user_grouping_respects_explicit_user_scope(self):
        first = self.make_file(upload_id="scopedA")
        second = self.make_file(user_id="user-b", upload_id="scopedB")
        self.update_row(first, summary="Only alpha content.")
        self.update_row(second, summary="Private beta content.")
        payloads = []

        def complete(tier, messages, response_format):
            payload = json.loads(messages[1]["content"])
            payloads.append(payload)
            self.assertNotIn("Private beta content", json.dumps(payload))
            self.assertEqual(response_format["json_schema"]["name"], "aggregate_user_summary")
            return self.user_response("Alpha user summary.", professional=["software"])

        with patch.object(aggregate_analysis, "complete", side_effect=complete):
            job = self.run_job({"user_id": "user-a", "group_by": "user"})
        result = json.loads(job["result_json"])
        self.assertEqual(job["user_id"], "user-a")
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["groups"], [{
            "user_id": "user-a",
            "file_count": 1,
            "total_duration_sec": 2.0,
            "summary": "Alpha user summary.",
            "professional_topics": ["software"],
            "personal_topics": [],
            "upcoming_events": [],
        }])
        self.assertEqual(result["overall_summary"], "Alpha user summary.")
        self.assertEqual(len(payloads), 1)

    def test_sentiment_groups_have_scoped_summaries(self):
        first = self.make_file(upload_id="sentimentA")
        second = self.make_file(upload_id="sentimentB")
        self.make_file(user_id="user-b", upload_id="sentimentOther")
        self.update_row(first, layer2_results=json.dumps({"sentiment": {"label": "positive"}}))
        self.update_row(second, summary="A gardener discussed planting.",
                        taxonomy=json.dumps({"professional_topics": [],
                                             "personal_topics": ["gardening"], "upcoming_events": []}))

        def complete(tier, messages, response_format):
            payload = json.loads(messages[1]["content"])
            if response_format["json_schema"]["name"] == "aggregate_analysis":
                return self.synthesis_response()
            summary = payload["records"][0]["summary"]
            return self.group_response("Software context." if "engineer" in summary else "Gardening context.")

        with patch.object(aggregate_analysis, "complete", side_effect=complete):
            job = self.run_job({"user_id": "user-a", "group_by": "sentiment"})
        result = json.loads(job["result_json"])
        self.assertEqual(result["groups"], [
            {"key": "positive", "file_count": 1, "total_duration_sec": 2.0,
             "summary": "Software context."},
            {"key": "unclassified", "file_count": 1, "total_duration_sec": 2.0,
             "summary": "Gardening context."},
        ])

    def test_taxonomy_groups_have_scoped_summaries(self):
        self.make_file(upload_id="taxonomyA")
        second = self.make_file(upload_id="taxonomyB")
        self.update_row(second, summary="A gardener discussed planting.",
                        taxonomy=json.dumps({"professional_topics": [],
                                             "personal_topics": ["gardening"], "upcoming_events": []}))

        def complete(tier, messages, response_format):
            payload = json.loads(messages[1]["content"])
            if response_format["json_schema"]["name"] == "aggregate_analysis":
                return self.synthesis_response()
            summary = payload["records"][0]["summary"]
            return self.group_response("Software group." if "engineer" in summary else "Gardening group.")

        with patch.object(aggregate_analysis, "complete", side_effect=complete):
            job = self.run_job({"user_id": "user-a", "group_by": "taxonomy"})
        result = json.loads(job["result_json"])
        self.assertEqual(result["groups"], [
            {"key": "gardening", "file_count": 1, "total_duration_sec": 2.0,
             "summary": "Gardening group."},
            {"key": "software", "file_count": 1, "total_duration_sec": 2.0,
             "summary": "Software group."},
        ])

    def test_no_matching_files_completes_without_llm(self):
        self.make_file(upload_id="aggregateNoMatch")
        with patch.object(aggregate_analysis, "complete", side_effect=AssertionError("LLM called")):
            job = self.run_job({
                "user_id": "user-a",
                "created_from": "2030-01-01T00:00:00Z",
                "group_by": "taxonomy",
            })
        result = json.loads(job["result_json"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(result, {
            "file_count": 0,
            "total_duration_sec": 0.0,
            "overall_summary": aggregate_analysis.NO_MATCH_SUMMARY,
            "professional_topics": [],
            "personal_topics": [],
            "upcoming_events": [],
            "group_by": "taxonomy",
            "groups": [],
        })

    def test_global_all_is_invalid_and_scoped_all_recovers(self):
        for body in (
            {"group_by": "all"},
            {"group_by": "arbitrary"},
            {"group_by": "user", "arbitrary": True},
            {"created_from": "2026-09-28T00:00:00Z", "created_to": "2026-09-27T00:00:00Z"},
            {"taxonomy_label": "   "},
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValidationError):
                    AggregateJobRequest.model_validate(body)
        self.assertNotIn("/aggregate-jobs", app.openapi()["paths"])

        self.make_file(upload_id="aggregateRecovery")
        request = AggregateJobRequest(user_id="user-a", group_by="all")
        job = aggregate_analysis.queue_aggregate_job(request)
        with patch.object(aggregate_analysis, "complete", return_value=self.synthesis_response()) as complete:
            aggregate_analysis.resume_aggregate_jobs([job["id"]])
        stored = database.get_aggregate_job(job["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(json.loads(stored["result_json"])["groups"], [{
            "key": "all",
            "file_count": 1,
            "total_duration_sec": 2.0,
            "summary": "The recordings discuss software and gardening.",
        }])
        self.assertEqual(complete.call_count, 1)
