import json
import sqlite3
import sys

from pathlib import Path

import pytest


# ==================================================
# 1. PROJECT IMPORTS
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SRC_PATH = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_PATH))

from nosh_ai.tasks import substitution


# ==================================================
# 2. SAMPLE LOCAL EVIDENCE
# ==================================================

def supported_evidence():

    return {

        "candidate_count": 100,

        "matching_recipe_count": 5,

        "same_method_count": 3,

        "direct_evidence_count": 0,

        "evidence": [

            {
                "recipe_id": "evidence-001",
                "title": "Pan Cooked Vegetables",
                "source_file": "test_recipes.json",
                "matching_ingredient_lines": [
                    "2 tablespoons olive oil"
                ],
                "preparation_methods": [
                    "pan_cooking"
                ],
                "shared_methods": [
                    "pan_cooking"
                ],
                "evidence_type": (
                    "indirect evidence: similar preparation method"
                ),
                "explicit_substitution": False,
            }

        ],

    }


def weak_evidence():

    return {

        "candidate_count": 100,

        "matching_recipe_count": 5,

        "same_method_count": 0,

        "direct_evidence_count": 0,

        "evidence": [],

    }


# ==================================================
# 3. TEMPORARY TEST DATABASE
# ==================================================

@pytest.fixture
def test_environment(tmp_path, monkeypatch):

    db_path = tmp_path / "test_substitution.db"

    connection = sqlite3.connect(db_path)

    connection.executescript(
        """
        CREATE TABLE recipes (
            recipe_id TEXT PRIMARY KEY,
            title_original TEXT,
            source_file TEXT,
            ingredients_original_json TEXT,
            instructions_original TEXT,
            has_instructions INTEGER
        );

        CREATE TABLE recipe_ingredients (
            recipe_id TEXT,
            position INTEGER,
            ingredient_original TEXT,
            is_searchable INTEGER
        );
        """
    )

    ingredients = [

        "5 ounces fresh scallops",
        "10 ounces crab meat",
        "2 ounces butter",
        "4 ounces bechamel",
        "1 tablespoon cubed carrots",
        "1 tablespoon cubed celery",
        "1 tablespoon cubed leeks",
        "1 tablespoon cubed daikon",
        "Butter, to fry",
        "1 cup lobster stock",
        "1 tablespoon lobster butter",
        "2 tablespoon cream",
        "1 tablespoon butter",
        "Chopped chives",
        "Salt, pepper",
        "1 large ravioli, cooked al dente",
        "Lotus root, sliced and fried",
        "Chives",

    ]

    instructions = (
        "For Crab Mousse: Finely chop the scallops and "
        "mix with the crabmeat in ice bowl. "
        "Saute in butter, and add bechamel. Hold warm.\n"

        "For Vegetables: Panfry the vegetables quickly "
        "in butter, until al dente.\n"

        "For Sauce: Reduce lobster stock by 1/2. "
        "Add lobster butter, cream, and 1 tablespoon butter.\n"

        "Assembly: Add the crab mousse and serve."
    )

    connection.execute(
        """
        INSERT INTO recipes (
            recipe_id,
            title_original,
            source_file,
            ingredients_original_json,
            instructions_original,
            has_instructions
        )
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (
            "crab-test",
            "Crab Big Ravioli",
            "test_recipes.json",
            json.dumps(ingredients),
            instructions,
        )
    )

    for position, line in enumerate(ingredients):

        connection.execute(
            """
            INSERT INTO recipe_ingredients (
                recipe_id,
                position,
                ingredient_original,
                is_searchable
            )
            VALUES (?, ?, ?, 1)
            """,
            (
                "crab-test",
                position,
                line,
            )
        )

    connection.commit()

    connection.close()

    # Use our temporary database instead of the
    # actual Nosh AI database.
    monkeypatch.setattr(
        substitution.matcher,
        "DB_PATH",
        db_path
    )

    # Use predictable local evidence for unit tests.
    monkeypatch.setattr(
        substitution,
        "search_local_evidence",
        lambda *args, **kwargs: supported_evidence()
    )

    return db_path


# ==================================================
# 4. HELPER TO RUN A SUBSTITUTION
# ==================================================

def run_test_substitution(
    recipe_id="crab-test",
    original="butter",
    replacement="olive oil",
    selected_line="2 ounces butter",
    instruction_context="Saute in butter",
):

    return substitution.build_substitution_plan(

        recipe_id=recipe_id,

        original_ingredient=original,

        replacement_ingredient=replacement,

        selected_ingredient_line=selected_line,

        instruction_context=instruction_context,

        evidence_limit=5,

    )


# ==================================================
# 5. TEST ONLY SELECTED INGREDIENT IS REPLACED
# ==================================================

def test_only_selected_butter_line_is_replaced(
    test_environment
):

    result = run_test_substitution()

    assert result["status"] == "supported_with_caveats"

    ingredients = result["revised_ingredients"]

    # Only the selected ingredient should change.
    # Its original quantity must be preserved.
    assert ingredients[2].startswith("2 ounces olive oil")

    # Other butter uses must remain unchanged.
    assert ingredients[8] == "Butter, to fry"

    assert ingredients[10] == "1 tablespoon lobster butter"

    assert ingredients[12] == "1 tablespoon butter"

    # The original source quantity must be preserved.
    assert ingredients[2] == "2 ounces olive oil"


# ==================================================
# 6. TEST ONLY SELECTED INSTRUCTION IS REVISED
# ==================================================

def test_only_selected_instruction_context_is_changed(
    test_environment
):

    result = run_test_substitution()

    instructions = result["revised_instructions"]

    assert "Saute in olive oil" in instructions

    assert "Panfry the vegetables quickly in butter" in instructions

    assert "Add lobster butter, cream, and 1 tablespoon butter" in instructions


# ==================================================
# 7. TEST COMPOUND BUTTER IS NOT SELECTED
# ==================================================

def test_lobster_butter_is_rejected_as_compound_ingredient(
    test_environment
):

    result = run_test_substitution(
        selected_line="1 tablespoon lobster butter"
    )

    assert (
        result["status"]
        == "compound_ingredient_not_selected"
    )

    assert result["revised_ingredients"] is None


# ==================================================
# 8. TEST INGREDIENT LINE NOT FOUND
# ==================================================

def test_missing_selected_ingredient_line(
    test_environment
):

    result = run_test_substitution(
        selected_line="3 tablespoons butter"
    )

    assert (
        result["status"]
        == "ingredient_line_not_found"
    )


# ==================================================
# 9. TEST INSTRUCTION CONTEXT NOT FOUND
# ==================================================

def test_instruction_context_not_found(
    test_environment
):

    result = run_test_substitution(
        instruction_context="Bake the crab mousse"
    )

    assert (
        result["status"]
        == "instruction_context_not_found"
    )

    assert result["revised_ingredients"] is None


# ==================================================
# 10. TEST AMBIGUOUS INSTRUCTION CONTEXT
# ==================================================

def test_ambiguous_instruction_context(
    test_environment
):

    connection = sqlite3.connect(
        test_environment
    )

    connection.execute(
        """
        UPDATE recipes
        SET instructions_original = ?
        WHERE recipe_id = ?
        """,
        (
            "Saute in butter. Later, saute in butter again.",
            "crab-test",
        )
    )

    connection.commit()

    connection.close()

    result = run_test_substitution()

    assert (
        result["status"]
        == "ambiguous_instruction_context"
    )

    assert result["revised_ingredients"] is None


# ==================================================
# 11. TEST AMBIGUOUS INGREDIENT ENTRY
# ==================================================

def test_duplicate_ingredient_line_is_rejected(
    test_environment
):

    connection = sqlite3.connect(
        test_environment
    )

    connection.execute(
        """
        INSERT INTO recipe_ingredients (
            recipe_id,
            position,
            ingredient_original,
            is_searchable
        )
        VALUES (?, ?, ?, 1)
        """,
        (
            "crab-test",
            18,
            "2 ounces butter",
        )
    )

    connection.commit()

    connection.close()

    result = run_test_substitution()

    assert (
        result["status"]
        == "ambiguous_ingredient_line"
    )


# ==================================================
# 12. TEST UNSUPPORTED SUBSTITUTION PAIR
# ==================================================

def test_unsupported_substitution_is_rejected(
    test_environment
):

    result = run_test_substitution(
        replacement="applesauce"
    )

    assert (
        result["status"]
        == "unsupported_substitution_pair"
    )

    assert result["revised_ingredients"] is None


# ==================================================
# 13. TEST WEAK LOCAL EVIDENCE
# ==================================================

def test_weak_local_evidence_is_rejected(
    test_environment,
    monkeypatch
):

    monkeypatch.setattr(
        substitution,
        "search_local_evidence",
        lambda *args, **kwargs: weak_evidence()
    )

    result = run_test_substitution()

    assert (
        result["status"]
        == "insufficient_local_evidence"
    )

    assert result["revised_ingredients"] is None

    assert result["revised_instructions"] is None


# ==================================================
# 14. TEST INCOMPATIBLE COOKING METHOD
# ==================================================

def test_baking_and_creaming_context_is_rejected(
    test_environment
):

    connection = sqlite3.connect(
        test_environment
    )

    connection.execute(
        """
        UPDATE recipes
        SET instructions_original = ?
        WHERE recipe_id = ?
        """,
        (
            "Cream butter and sugar until fluffy, then bake.",
            "crab-test",
        )
    )

    connection.commit()

    connection.close()

    result = run_test_substitution(
        instruction_context=(
            "Cream butter and sugar until fluffy, then bake"
        )
    )

    assert (
        result["status"]
        == "incompatible_preparation_context"
    )

    assert result["revised_ingredients"] is None


# ==================================================
# 15. TEST UNKNOWN RECIPE ID
# ==================================================

def test_unknown_recipe_id_is_rejected(
    test_environment
):

    result = run_test_substitution(
        recipe_id="unknown-recipe-id"
    )

    assert result["status"] == "recipe_not_found"


# ==================================================
# 16. TEST DIRECT AND INDIRECT EVIDENCE LABELS
# ==================================================

def test_indirect_evidence_is_not_labelled_as_direct(
    test_environment
):

    result = run_test_substitution()

    assert result["status"] == "supported_with_caveats"

    assert result["direct_substitution_evidence_count"] == 0

    assert result["same_method_evidence_count"] == 3

    assert result["evidence"][0]["explicit_substitution"] is False

    assert (
        result["evidence"][0]["evidence_type"]
        == "indirect evidence: similar preparation method"
    )

    assert (
        "Not performed"
        in result["experimental_verification"]
    )
