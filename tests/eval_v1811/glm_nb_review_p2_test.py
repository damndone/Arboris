"""Targeted independent assertions; consumes only safe proof metadata."""
from pathlib import Path
import json

PROOF=json.loads(Path(__file__).with_name("glm_nb_review_p2_proof.json").read_text())

def test_complete_raw_logs_preserved_ignored_with_original_hashes():
    assert len(PROOF["records"])==4
    assert all(r["raw_equals_before_git"] and r["raw_ignored_and_untracked"] and r["raw_mode_0600"]
               for r in PROOF["records"])

def test_only_eight_header_values_changed_with_exact_payload_and_manifest():
    assert PROOF["changed_header_lines_total"]==8
    assert all(r["exact_header_only_redaction"] and r["payload_byte_identical"] and r["manifest_hashes_match"]
               and r["manifest_line_numbers_match"] for r in PROOF["records"])

def test_current_new_public_texts_contain_no_original_license_value():
    assert PROOF["added_tracked_texts_scanned"]>=49
    assert not PROOF["private_field_value_hits"]
    assert not PROOF["unredacted_header_hits"]

def test_prior_statistics_and_all_existing_author_test_functions_unchanged():
    assert len(PROOF["unchanged_statistical_assets"])==19
    assert all(x["unchanged"] for x in PROOF["unchanged_statistical_assets"])
    assert PROOF["existing_author_functions_ast_unchanged"]
    assert PROOF["original_independent_evidence_hashes_unchanged"]

def test_nine_frozen_protected_assets_and_updated_manifest_match():
    assert len(PROOF["protected"])==9
    assert all(x["baseline_identical"] and x["manifest_matches"] for x in PROOF["protected"])
    assert PROOF["current_manifest_asset_hashes_match"]
