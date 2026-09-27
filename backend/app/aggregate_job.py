import argparse
import json

from pydantic import ValidationError

from app.aggregate_analysis import queue_aggregate_job, run_aggregate_job
from app.database import get_aggregate_job, init_db, migrate_storage
from app.models import AggregateJobRequest


def parser():
    value = argparse.ArgumentParser()
    value.add_argument("--group-by", choices=("all", "user", "taxonomy", "sentiment"), default="user")
    value.add_argument("--user-id")
    value.add_argument("--created-from")
    value.add_argument("--created-to")
    value.add_argument("--taxonomy-label")
    return value


def main():
    argument_parser = parser()
    arguments = argument_parser.parse_args()
    try:
        request = AggregateJobRequest(
            user_id=arguments.user_id,
            created_from=arguments.created_from,
            created_to=arguments.created_to,
            taxonomy_label=arguments.taxonomy_label,
            group_by=arguments.group_by,
        )
    except ValidationError as error:
        argument_parser.error(str(error))
    init_db()
    migrate_storage()
    job = queue_aggregate_job(request)
    print(json.dumps({"job_id": job["id"], "status": job["status"]}))
    run_aggregate_job(job["id"])
    job = get_aggregate_job(job["id"])
    result = json.loads(job["result_json"]) if job["result_json"] else None
    print(json.dumps({"job_id": job["id"], "status": job["status"],
                      "result": result, "error": job["error"]}, indent=2))
    return 0 if job["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
