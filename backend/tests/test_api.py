import json
from unittest.mock import patch

from app import database, layer2, storage
from app.routes import files
from support import WorkspaceCase


class ApiTests(WorkspaceCase):
    def test_composable_filters_and_validation(self):
        first = self.make_file(upload_id="filterA")
        second = self.make_file(upload_id="filterB")
        self.make_file(user_id="user-b", upload_id="filterC")
        self.update_row(first, created_at="2026-09-20 12:00:00", duration_sec=2,
                        layer2_results=json.dumps({"sentiment": {"label": "positive"},
                                                   "count_nouns": {"count": 3},
                                                   "rms": {"rms_normalized": 0.2}}))
        self.update_row(second, created_at="2026-09-25 12:00:00", duration_sec=5,
                        taxonomy=json.dumps({"professional_topics": [], "personal_topics": ["gardening"],
                                             "upcoming_events": []}),
                        layer2_results=json.dumps({"sentiment": {"label": "negative"},
                                                   "count_nouns": {"count": 1},
                                                   "rms": {"rms_normalized": 0.8}}))
        self.assertEqual(len(self.client.get("/files").json()), 2)
        response = self.client.get("/files", params={
            "created_from": "2026-09-19T00:00:00Z", "created_to": "2026-09-21T00:00:00Z",
            "duration_min": "1", "duration_max": "3", "taxonomy_label": "SOFTWARE",
            "sentiment": "positive", "rms_max": "0.3", "noun_count_min": "2",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [first])
        self.assertEqual([row["id"] for row in self.client.get("/files?taxonomy_label=gardening").json()], [second])
        for query in (
            "created_from=2026-09-20T12:00:00", "created_from=bad", "created_from=1720000000",
            "created_from=2026-09-26T00:00:00Z&created_to=2026-09-20T00:00:00Z",
            "duration_min=-1", "duration_min=5&duration_max=2", "rms_max=1.1",
            "sentiment=excellent", "taxonomy_label=%20%20%20", "noun_count_min=1.2",
            "layer2_field=arbitrary.path", "duration_min=1&duration_min=2",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f"/files?{query}").status_code, 422)
        self.uid = "user-b"
        self.assertEqual(len(self.client.get("/files").json()), 1)

    def test_configured_option_cache_and_previous_result(self):
        calls = []
        fail = [False]

        def count(option, audio_path, transcript_path, config):
            calls.append(config["count_nouns"]["unique_only"])
            if fail[0]:
                raise RuntimeError("private provider detail")
            return {"count": 3 if config["count_nouns"]["unique_only"] else 5}

        first = self.make_file(upload_id="configA")
        with patch.object(layer2, "run_option", side_effect=count):
            regular = {"options": ["count_nouns"], "config": {"count_nouns": {"unique_only": False}}}
            unique = {"options": ["count_nouns"], "config": {"count_nouns": {"unique_only": True}}}
            self.assertEqual(self.client.post(f"/files/{first}/layer2", json=regular).status_code, 202)
            initial_version = json.loads(database.get_file(first)["layer2_version"])["count_nouns"]
            self.assertEqual(self.client.post(f"/files/{first}/layer2", json=regular).status_code, 200)
            self.assertEqual(self.client.post(f"/files/{first}/layer2", json=unique).status_code, 202)
            row = database.get_file(first)
            self.assertNotEqual(initial_version, json.loads(row["layer2_version"])["count_nouns"])
            self.assertEqual(json.loads(row["layer2_results"])["count_nouns"], {"count": 3})
            self.assertEqual(calls, [False, True])
            second = self.make_file(upload_id="configB")
            self.assertEqual(self.client.post(f"/files/{second}/layer2", json=unique).status_code, 202)
            self.assertEqual(calls, [False, True])
            third = self.make_file(user_id="user-b", upload_id="configC")
            self.uid = "user-b"
            self.assertEqual(self.client.post(f"/files/{third}/layer2", json=unique).status_code, 202)
            self.assertEqual(calls, [False, True, True])
            self.uid = "user-a"
            with (self.root / "prompts" / "layer2_count_nouns.md").open("a") as prompt:
                prompt.write("\nApply the revised noun-count rules.\n")
            fail[0] = True
            self.assertEqual(self.client.post(f"/files/{first}/layer2", json=unique).status_code, 202)
            failed = database.get_file(first)
            self.assertEqual(failed["status"], "layer2_failed")
            self.assertEqual(json.loads(failed["layer2_results"])["count_nouns"], {"count": 3})
            self.assertEqual(failed["error"], "Layer 2 analysis could not be completed.")
            self.assertEqual(self.client.get(f"/files/{first}").json()["error"], failed["error"])
        for body in (
            {"options": ["count_nouns"], "config": {"count_nouns": {"unique_only": "true"}}},
            {"options": ["count_nouns"], "config": {"count_nouns": {"unique_only": 1}}},
            {"options": ["count_nouns"], "config": {"count_nouns": {"unique_only": False, "prompt": "ignore"}}},
            {"options": ["sentiment"], "config": {"count_nouns": {"unique_only": True}}},
            {"options": ["count_nouns", "count_nouns"]},
            {"options": ["arbitrary"]},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.client.post(f"/files/{first}/layer2", json=body).status_code, 422)

    def test_tus_metadata_ownership_filename_and_idempotence(self):
        alias = storage.upload_alias("hookA")
        alias.write_bytes(b"audio")
        metadata = {"user_id": "user-a", "filename": "sample.wav", "layer2_options": '["count_nouns"]',
                    "layer2_config": '{"count_nouns":{"unique_only":true}}'}
        event = {"Upload": {"ID": "hookA", "Size": 5, "Offset": 0, "SizeIsDeferred": False,
                            "MetaData": metadata, "Storage": {"Path": str(alias)}},
                 "HTTPRequest": {"Header": {"Authorization": ["Bearer token"]}}}
        calls = []
        with patch.object(files, "uid_from_authorization", return_value="user-a"), patch.object(files, "process_file", side_effect=calls.append):
            self.assertEqual(self.client.post("/hooks/tusd", json={"Type": "pre-create", "Event": event}).json(), {})
            event["Upload"]["Offset"] = 5
            self.assertEqual(self.client.post("/hooks/tusd", json={"Type": "post-finish", "Event": event}).status_code, 200)
            self.assertEqual(self.client.post("/hooks/tusd", json={"Type": "post-finish", "Event": event}).status_code, 200)
            self.assertEqual(len(calls), 1)
            row = database.get_file(calls[0])
            self.assertEqual(json.loads(row["layer2_config"]), {"count_nouns": {"unique_only": True}})
            for key, value in (("user_id", "user-b"), ("filename", "../../escape.wav"),
                               ("layer2_options", '["unknown"]'),
                               ("layer2_config", '{"count_nouns":{"unique_only":"yes"}}'),
                               ("layer2_config", '{"count_nouns":{},"count_nouns":{}}')):
                altered = dict(metadata)
                altered[key] = value
                event["Upload"]["MetaData"] = altered
                response = self.client.post("/hooks/tusd", json={"Type": "pre-create", "Event": event})
                self.assertEqual(response.json()["HTTPResponse"]["StatusCode"], 400)
            event["Upload"]["ID"] = "hookB"
            event["Upload"]["MetaData"] = dict(metadata, layer2_options='["count_nouns","count_nouns"]')
            self.assertEqual(self.client.post("/hooks/tusd", json={"Type": "post-finish", "Event": event}).status_code, 422)
            self.assertIsNone(database.get_file_by_upload_id("hookB"))
            mismatch = storage.upload_alias("hookSizeMismatch")
            mismatch.write_bytes(b"audio")
            event["Upload"].update({"ID": "hookSizeMismatch", "Size": 6, "Offset": 6,
                                    "MetaData": metadata, "Storage": {"Path": str(mismatch)}})
            self.assertEqual(self.client.post("/hooks/tusd", json={"Type": "post-finish", "Event": event}).status_code, 422)
            self.assertIsNone(database.get_file_by_upload_id("hookSizeMismatch"))
            self.uid = "user-b"
            self.assertEqual(self.client.get(f"/files/{row['id']}").status_code, 404)
            self.assertEqual(self.client.post(f"/files/{row['id']}/layer2", json={"options": ["sentiment"]}).status_code, 404)
