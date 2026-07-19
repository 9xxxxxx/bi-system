import json
from pathlib import Path
from typing import cast

from scripts import export_m3_permission_evidence as exporter


def test_export_permission_evidence_writes_complete_fail_closed_matrix(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "permission-evidence"

    result = exporter.export_permission_evidence(output_dir, rows=14)

    assert result == 0
    assert {path.name for path in output_dir.iterdir()} == set(exporter.MATRIX_FILES.values())
    documents = {
        matrix_id: _read_json(output_dir / filename)
        for matrix_id, filename in exporter.MATRIX_FILES.items()
    }
    for matrix_id, document in documents.items():
        assert document["schema_version"] == 1
        assert document["matrix_id"] == matrix_id
        assert document["status"] == "pass"
        assert document["fixture_version"] == "m3-star-v2"
        assert len(cast(str, document["fixture_manifest_sha256"])) == 64
        assert len(cast(str, document["git_sha"])) == 40
        assert cast(list[object], document["cases"])
        assert all(cast(dict[str, bool], document["checks"]).values())
        provenance = cast(dict[str, object], document["producer_provenance"])
        source_hashes = cast(dict[str, object], provenance["source_content_sha256"])
        assert "permission_evidence_exporter" in source_hashes
        assert len(cast(str, provenance["worktree_snapshot_sha256"])) == 64
        fixture = cast(dict[str, object], document["benchmark_fixture_provenance"])
        assert fixture["requested_rows"] == fixture["fact_row_count"] == 14
        assert len(cast(str, fixture["benchmark_manifest_sha256"])) == 64
        assert fixture["all_files_verified"] is True
        assert fixture["trust_anchor_verified"] is True
        fixture_files = cast(dict[str, dict[str, object]], fixture["files"])
        assert set(fixture_files) == {
            "fact_sales.csv",
            "dim_product.csv",
            "dim_region.csv",
            "schema.json",
        }
        assert all(item["verified"] is True for item in fixture_files.values())
        assert provenance["benchmark_fixture"] == fixture

    principal_cases = cast(list[dict[str, object]], documents["M3-P01"]["cases"])
    assert {item["principal_name"] for item in principal_cases} == {
        "administrator",
        "editor",
        "restricted_viewer",
    }
    assert all(item["principal_id"] and item["dataset_id"] for item in principal_cases)
    assert all(len(cast(str, item["result_sha256"])) == 64 for item in principal_cases)
    assert all(cast(list[object], item["canonical_rows"]) for item in principal_cases)

    rls = documents["M3-P02"]
    assert cast(dict[str, bool], rls["checks"])["rls_applied_before_aggregation"] is True
    assert cast(dict[str, bool], rls["checks"])["application_result_cache_absent"] is True
    assert cast(dict[str, bool], rls["checks"])["tooltip_uses_restricted_query_rows"] is True
    rls_case = cast(list[dict[str, object]], rls["cases"])[0]
    cache = cast(dict[str, object], rls_case["cache"])
    assert cast(int, cache["first_fact_select_count"]) > 0
    assert cast(int, cache["second_fact_select_count"]) > 0
    assert cache["first_restricted_result_sha256"] == cache["repeated_restricted_result_sha256"]
    assert len(cast(str, cache["direct_query_source_sha256"])) == 64

    forged_cases = cast(list[dict[str, object]], documents["M3-P03"]["cases"])
    assert forged_cases[0]["canonical_rows"] == []
    assert forged_cases[1]["accepted"] is False
    assert forged_cases[1]["error_code"] == "extra_forbidden"

    cross_cases = cast(list[dict[str, object]], documents["M3-P04"]["cases"])
    assert {item["resource"] for item in cross_cases} == {
        "dashboard",
        "dataset",
        "field",
        "query",
    }
    assert all(item["resource_id"] for item in cross_cases)
    assert all(item["status_code"] == 404 for item in cross_cases)
    query_case = next(item for item in cross_cases if item["resource"] == "query")
    assert query_case["query_executed"] is False

    capability_cases = cast(list[dict[str, object]], documents["M3-P05"]["cases"])
    capability_by_name = {cast(str, item["case"]): item for item in capability_cases}
    assert set(capability_by_name) == {
        "editor-dataset-manage",
        "viewer-dashboard-edit",
    }
    assert capability_by_name["editor-dataset-manage"]["status_code"] == 403
    assert capability_by_name["editor-dataset-manage"]["error_code"] == "dataset_manage_forbidden"
    assert capability_by_name["viewer-dashboard-edit"]["status_code"] == 403
    assert capability_by_name["viewer-dashboard-edit"]["error_code"] == "dashboard_forbidden"
    assert all(item["before"] == item["after"] for item in capability_cases)
    assert all(item["no_partial_write"] is True for item in capability_cases)


def test_document_cannot_pass_without_checks_cases_or_stable_context() -> None:
    provenance: dict[str, object] = {"head_sha": "a" * 40}

    missing_cases = exporter.build_evidence_document(
        matrix_id="M3-P01",
        fixture_version="m3-star-v2",
        fixture_manifest_sha256="b" * 64,
        producer_provenance=provenance,
        benchmark_fixture_provenance=None,
        checks={"subjects_present": True},
        cases=[],
    )
    failed_check = exporter.build_evidence_document(
        matrix_id="M3-P05",
        fixture_version="m3-star-v2",
        fixture_manifest_sha256="b" * 64,
        producer_provenance=provenance,
        benchmark_fixture_provenance=None,
        checks={"before_after_present": False},
        cases=[{"error_code": "dashboard_forbidden"}],
    )
    unstable_error = exporter.build_evidence_document(
        matrix_id="M3-P04",
        fixture_version="m3-star-v2",
        fixture_manifest_sha256="b" * 64,
        producer_provenance=provenance,
        benchmark_fixture_provenance=None,
        checks={"query_not_executed": True},
        cases=[{"query_executed": False}],
        error_code="evidence_document_missing",
    )

    assert missing_cases["status"] == "fail"
    assert failed_check["status"] == "fail"
    assert unstable_error["status"] == "fail"


def test_parse_args_requires_output_directory() -> None:
    args = exporter.parse_args(["--output-dir", "evidence", "--rows", "10"])

    assert args.output_dir == Path("evidence")
    assert args.rows == 10


def _read_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
