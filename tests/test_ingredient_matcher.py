
import json
import sqlite3
import sys

from pathlib import Path

import pytest


# Make the project's src folder importable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

SRC_PATH = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_PATH))

from nosh_ai.retrieval import ingredient_matcher as matcher


# ==================================================
# 1. TEMPORARY TEST DATABASE
# ==================================================

@pytest.fixture
def test_database(tmp_path, monkeypatch):

    db_path = tmp_path / "test_recipes.db"

    connection = sqlite3.connect(db_path)

    connection.executescript(
        """
        CREATE TABLE recipes (
            recipe_id TEXT PRIMARY KEY,
            title_original TEXT,
            source_file TEXT,
            ingredients_original_json TEXT,
            instructions_original TEXT,
            has_title INTEGER,
            has_ingredients INTEGER
        );

        CREATE TABLE recipe_ingredients (
            recipe_id TEXT,
            position INTEGER,
            ingredient_original TEXT,
            is_searchable INTEGER,
            PRIMARY KEY (recipe_id, position)
        );
        """
    )

    records = [

        {
            "id": "exact",
            "title": "Garlic Onion Rice",
            "ingredients": [
                "2 cloves garlic, minced",
                "1 onion, chopped",
                "1 cup rice",
            ],
            "instructions": (
                "Step 1: Chop the garlic and onion.\n"
                "Step 2: Cook the ingredients.\n"
                "Step 3: Serve."
            ),
        },

        {
            "id": "partial",
            "title": "Garlic Toast",
            "ingredients": [
                "1 clove garlic, minced",
                "2 slices bread",
            ],
            "instructions": "Toast the bread.",
        },

        {
            "id": "peanut",
            "title": "Peanut Garlic Onion Rice",
            "ingredients": [
                "2 cloves garlic",
                "1 onion",
                "1/2 cup peanuts",
            ],
            "instructions": "Mix and cook.",
        },

        {
            "id": "insufficient",
            "title": "Small Garlic Onion Rice",
            "ingredients": [
                "1 clove garlic",
                "1 onion",
                "1 cup rice",
            ],
            "instructions": "Cook the ingredients.",
        },

        {
            "id": "sufficient",
            "title": "Garlic Onion Rice Bowl",
            "ingredients": [
                "3 cloves garlic",
                "2 onions",
                "1 cup rice",
            ],
            "instructions": (
                "Step 1: Prepare the ingredients.\n"
                "Step 2: Cook and serve."
            ),
        },

        {
            "id": "alias",
            "title": "Chickpea Bowl",
            "ingredients": [
                "1 cup chickpeas",
            ],
            "instructions": "Mix and serve.",
        },

        {
            "id": "no_steps",
            "title": "Garlic Onion Salad",
            "ingredients": [
                "1 clove garlic",
                "1 onion",
            ],
            "instructions": None,
        },

        {
            "id": "no_match",
            "title": "Plain Rice",
            "ingredients": [
                "2 cups rice",
            ],
            "instructions": "Cook the rice.",
        },

    ]

    for record in records:

        connection.execute(
            """
            INSERT INTO recipes (
                recipe_id,
                title_original,
                source_file,
                ingredients_original_json,
                instructions_original,
                has_title,
                has_ingredients
            )
            VALUES (?, ?, ?, ?, ?, 1, 1)
            """,
            (
                record["id"],
                record["title"],
                "test_recipes.json",
                json.dumps(record["ingredients"]),
                record["instructions"],
            )
        )

        for position, line in enumerate(
            record["ingredients"]
        ):

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
                    record["id"],
                    position,
                    line,
                )
            )

    connection.commit()

    connection.close()

    # Direct the matcher to the temporary database.
    # Your actual 1.06 GB database is not modified.
    monkeypatch.setattr(
        matcher,
        "DB_PATH",
        db_path
    )

    return records


# ==================================================
# 2. BASIC INGREDIENT MATCHING
# ==================================================

def test_exact_ingredient_match(test_database):

    output = matcher.match_recipes(
        ingredients=["garlic", "onion"],
        hard_exclusions=["peanuts"],
        max_missing=0,
        limit=100,
    )

    results = {
        recipe["recipe_id"]: recipe
        for recipe in output["results"]
    }

    assert "exact" in results

    recipe = results["exact"]

    assert recipe["matched_count"] == 2

    assert recipe["missing_count"] == 0

    assert recipe["coverage"] == 1.0

    assert recipe["additional_ingredients"] == [
        "1 cup rice"
    ]


# ==================================================
# 3. PARTIAL MATCHING AND MISSING INGREDIENTS
# ==================================================

def test_partial_match_reports_missing_ingredients(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["garlic", "onion"],
        hard_exclusions=["peanuts"],
        max_missing=1,
        limit=100,
    )

    results = {
        recipe["recipe_id"]: recipe
        for recipe in output["results"]
    }

    assert "partial" in results

    recipe = results["partial"]

    assert recipe["matched_count"] == 1

    assert recipe["missing_ingredients"] == [
        "onion"
    ]

    assert recipe["coverage"] == 0.5


# ==================================================
# 4. HARD EXCLUSION
# ==================================================

def test_hard_exclusion_blocks_peanut_recipe(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["garlic", "onion"],
        hard_exclusions=["peanuts"],
        limit=100,
    )

    returned_ids = {
        recipe["recipe_id"]
        for recipe in output["results"]
    }

    assert "peanut" not in returned_ids

    assert output["recipes_blocked_by_exclusion"] == 1


# ==================================================
# 5. STRICT MATCHING
# ==================================================

def test_zero_missing_rejects_partial_recipes(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["garlic", "onion"],
        hard_exclusions=["peanuts"],
        max_missing=0,
        limit=100,
    )

    returned_ids = {
        recipe["recipe_id"]
        for recipe in output["results"]
    }

    assert "partial" not in returned_ids

    assert "exact" in returned_ids

    assert output["partial_matches"] == 0


# ==================================================
# 6. QUANTITY SUFFICIENCY
# ==================================================

def test_quantity_sufficiency_and_insufficiency(
    test_database
):

    output = matcher.match_recipes(
        ingredients=[
            "2 cloves garlic",
            "1 onion",
        ],
        limit=100,
    )

    results = {
        recipe["recipe_id"]: recipe
        for recipe in output["results"]
    }

    # Three cloves garlic and two onions are sufficient.
    sufficient = results["sufficient"]

    assert (
        sufficient["matched_ingredients"]
        ["2 cloves garlic"]["quantity_status"]
        == "sufficient"
    )

    assert (
        sufficient["matched_ingredients"]
        ["1 onion"]["quantity_status"]
        == "sufficient"
    )

    # One clove garlic is insufficient for two cloves.
    insufficient = results["insufficient"]

    assert (
        insufficient["matched_ingredients"]
        ["2 cloves garlic"]["quantity_status"]
        == "insufficient"
    )

    # One onion is sufficient for the requested one onion.
    assert (
        insufficient["matched_ingredients"]
        ["1 onion"]["quantity_status"]
        == "sufficient"
    )


# ==================================================
# 7. INGREDIENT ALIASES
# ==================================================

def test_garbanzo_bean_alias_matches_chickpeas(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["garbanzo beans"],
        limit=100,
    )

    returned_ids = {
        recipe["recipe_id"]
        for recipe in output["results"]
    }

    assert "alias" in returned_ids


# ==================================================
# 8. NO-MATCH SCENARIO
# ==================================================

def test_no_match_returns_empty_results(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["saffron"],
        limit=5,
    )

    assert output["results"] == []

    assert output["recipes_with_any_match"] == 0

    assert output["recipes_qualifying"] == 0


# ==================================================
# 9. MISSING INSTRUCTIONS
# ==================================================

def test_missing_instructions_are_reported(
    test_database
):

    output = matcher.match_recipes(
        ingredients=["garlic", "onion"],
        limit=100,
    )

    results = {
        recipe["recipe_id"]: recipe
        for recipe in output["results"]
    }

    recipe = results["no_steps"]

    assert recipe["estimated_steps"] is None

    assert recipe["step_estimate_method"] == "unavailable"


# ==================================================
# 10. INSTRUCTION STEP ESTIMATION
# ==================================================

def test_numbered_step_estimation():

    instructions = (
        "Step 1: Chop garlic. "
        "Step 2: Chop onion. "
        "Step 3: Cook."
    )

    steps, method = matcher.estimate_instruction_steps(
        instructions
    )

    assert steps == 3

    assert method == "numbered-step estimate"


def test_bullet_step_estimation():

    instructions = (
        "- Chop garlic.\n"
        "- Chop onion.\n"
        "- Cook."
    )

    steps, method = matcher.estimate_instruction_steps(
        instructions
    )

    assert steps == 3

    assert method == "bullet-step estimate"


def test_line_based_step_estimation():

    instructions = (
        "Chop garlic and onion.\n"
        "Add rice and water.\n"
        "Cook and serve."
    )

    steps, method = matcher.estimate_instruction_steps(
        instructions
    )

    assert steps == 3

    assert method == "line-based estimate"


def test_paragraph_is_only_a_sentence_proxy():

    instructions = (
        "Chop garlic. Add onion. Cook everything."
    )

    steps, method = matcher.estimate_instruction_steps(
        instructions
    )

    assert steps == 3

    assert (
        method
        == "sentence-count proxy (not verified steps)"
    )


def test_empty_instructions_are_unavailable():

    steps, method = matcher.estimate_instruction_steps(
        None
    )

    assert steps is None

    assert method == "unavailable"


# ==================================================
# 11. STEP RANKING DOES NOT TRUST SENTENCE PROXIES
# ==================================================

def test_sentence_proxy_does_not_control_step_ranking():

    base = {
        "matched_count": 2,
        "missing_count": 0,
        "quantity_insufficient_count": 0,
        "quantity_unverified_count": 0,
        "quantity_sufficient_count": 0,
        "additional_count": 2,
        "title": "Test Recipe",
        "recipe_id": "test",
    }

    structured = {
        **base,
        "estimated_steps": 4,
        "step_estimate_method": "numbered-step estimate",
    }

    sentence_proxy = {
        **base,
        "estimated_steps": 1,
        "step_estimate_method": (
            "sentence-count proxy (not verified steps)"
        ),
    }

    structured_key = matcher.ranking_key(
        structured,
        prefer_fewer_steps=True
    )

    proxy_key = matcher.ranking_key(
        sentence_proxy,
        prefer_fewer_steps=True
    )

    # A sentence proxy must not rank ahead of
    # a recipe with a structured step estimate.
    assert structured_key[0] < proxy_key[0]
    
def test_generic_garlic_rejects_garlic_marinade():

    requested = matcher.parse_ingredient_spec("garlic")

    assert not matcher.ingredient_name_matches(
        requested,
        "1 1/4 cups herb-garlic marinade"
    )

    assert matcher.ingredient_name_matches(
        requested,
        "2 cloves fresh garlic, minced"
    )