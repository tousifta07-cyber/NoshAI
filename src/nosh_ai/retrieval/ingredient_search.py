
import argparse
import json
import re
import sqlite3

from pathlib import Path


# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "recipes.db"
)


# ==================================================
# 2. INGREDIENT FORM EXCLUSIONS
# ==================================================

# These exclusions apply only to generic searches for
# garlic or onion. They do not block explicit searches
# such as "garlic powder".

FORM_EXCLUSIONS = {

    "garlic": [

        r"\bgarlic\s+(?:powder|salt|seasoning|sauce|butter|oil|paste|spread|blend|mix)\b",

        r"\bpowdered\s+garlic\b",

        r"\bgranulated\s+garlic\b",

        r"\b(?:chile|chili)[-\s]+garlic\s+sauce\b",

        # Compound seasonings are not direct garlic.
        r"\bgarlic\s+pepper\b",

        # Prepared spaghetti sauce is not direct garlic.
        r"\bonion\s+and\s+garlic\s+spaghetti\s+sauce\b",

        r"\bgarlic\s+spaghetti\s+sauce\b",

        # Covers named compound products such as:
        # mango garlic seafood seasoning.
        r"\b(?:[a-z-]+\s+){0,3}garlic(?:\s+[a-z-]+){0,2}\s+seasoning\b",

    ],

    "onion": [

        r"\bonion\s+(?:powder|salt|soup\s+mix|flakes?|seasoning|dip|mix)\b",

        r"\bpowdered\s+onions?\b",

        r"\b(?:dry|dried|dehydrated)\s+(?:minced\s+)?onions?\b",

        r"\b(?:green|spring)\s+onions?\b",

        r"\bscallions?\b",

        r"\bshallots?\b",

        # Prepared spaghetti sauce is not direct onion.
        r"\bonion\s+and\s+garlic\s+spaghetti\s+sauce\b",

    ],

}


# ==================================================
# 3. TEXT CLEANING PATTERNS
# ==================================================

# Removes parenthetical explanations from a temporary
# matching copy. Original ingredient text is preserved.
#
# Example:
# "steak dust (recommended: garlic and onion)"
# becomes:
# "steak dust"

PARENTHETICAL_PATTERN = re.compile(
    r"\([^)]*\)"
)


ADVERTISEMENT_PATTERN = re.compile(
    r"\bADVERTISEMENT\b",
    re.IGNORECASE
)


# ==================================================
# 4. DATABASE CONNECTION
# ==================================================

def get_connection():

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    connection = sqlite3.connect(
        DB_PATH,
        timeout=60
    )

    connection.row_factory = sqlite3.Row

    return connection


# ==================================================
# 5. NORMALIZE USER INGREDIENTS
# ==================================================

def normalize_requested_ingredient(ingredient):

    if not isinstance(ingredient, str):

        return ""

    words = re.findall(
        r"[a-zA-Z0-9]+",
        ingredient.casefold()
    )

    return " ".join(words)


# ==================================================
# 6. BUILD FTS5 SEARCH QUERY
# ==================================================

def build_ingredient_query(ingredients):

    clauses = []

    for ingredient in ingredients:

        words = ingredient.split()

        if not words:
            continue

        safe_words = [
            f'"{word}"'
            for word in words
        ]

        word_query = " AND ".join(safe_words)

        clauses.append(
            f"ingredients : ({word_query})"
        )

    return " AND ".join(clauses)


# ==================================================
# 7. VERIFY ONE INGREDIENT LINE
# ==================================================

def matches_ingredient_line(
    ingredient_line,
    requested_ingredient
):

    """
    Validate an individual ingredient entry.

    Parenthetical explanations are removed from a
    temporary matching copy.

    Different ingredient forms are excluded for
    generic garlic and onion searches.

    The original ingredient line is never modified.
    """

    if not isinstance(ingredient_line, str):

        return False

    text = ingredient_line.casefold()

    # Remove advertisement markers.
    text = ADVERTISEMENT_PATTERN.sub(
        " ",
        text
    )

    # Remove explanatory parenthetical text.
    text = PARENTHETICAL_PATTERN.sub(
        " ",
        text
    )

    # Normalize whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    # Exclude different product forms.
    for pattern in FORM_EXCLUSIONS.get(
        requested_ingredient,
        []
    ):

        if re.search(pattern, text):

            return False

    # Every requested word must occur in this
    # individual ingredient entry.
    for word in requested_ingredient.split():

        pattern = rf"\b{re.escape(word)}s?\b"

        if not re.search(pattern, text):

            return False

    return True


# ==================================================
# 8. CREATE A RECIPE CANDIDATE
# ==================================================

def create_candidate(row):

    original_json = row[
        "ingredients_original_json"
    ]

    if original_json:

        original_ingredients = json.loads(
            original_json
        )

    else:

        original_ingredients = []

    return {

        "recipe_id": row["recipe_id"],

        "title": row["title_original"],

        "source_file": row["source_file"],

        "ingredients": original_ingredients,

        "instructions": row["instructions_original"],

        "relevance_score": row["relevance_score"],

        "ingredient_entries": [],

    }


# ==================================================
# 9. VALIDATE A COMPLETE CANDIDATE
# ==================================================

def validate_candidate(
    candidate,
    requested
):

    matched = {}

    for requested_ingredient in requested:

        matching_lines = [

            line

            for line in candidate["ingredient_entries"]

            if matches_ingredient_line(
                line,
                requested_ingredient
            )

        ]

        if matching_lines:

            matched[requested_ingredient] = matching_lines

    # A recipe must contain every requested ingredient.
    if len(matched) != len(requested):

        return None

    return {

        "recipe_id": candidate["recipe_id"],

        "title": candidate["title"],

        "source_file": candidate["source_file"],

        "ingredients": candidate["ingredients"],

        "instructions": candidate["instructions"],

        "matched_ingredients": matched,

        "relevance_score": candidate["relevance_score"],

    }


# ==================================================
# 10. SEARCH RECIPES
# ==================================================

def search_by_ingredients(
    ingredients,
    limit=10
):

    """
    Return top BM25-ranked recipes that pass
    individual ingredient-line validation.

    There is no arbitrary 20,000-candidate cutoff.

    Processing stops after collecting the requested
    number of verified results.

    This is a top-results search, not a complete
    ingredient-match count or ranking operation.
    """

    if not isinstance(limit, int) or not 1 <= limit <= 100:

        raise ValueError(
            "Limit must be between 1 and 100."
        )

    # ----------------------------------------------
    # Normalize and deduplicate requested ingredients
    # ----------------------------------------------

    requested = []

    for ingredient in ingredients:

        normalized = normalize_requested_ingredient(
            ingredient
        )

        if normalized and normalized not in requested:

            requested.append(normalized)

    if not requested:

        return {

            "results": [],

            "candidate_count": 0,

            "candidates_examined": 0,

            "stopped_after_limit": False,

            "requested_ingredients": [],

        }

    fts_query = build_ingredient_query(
        requested
    )

    if not fts_query:

        return {

            "results": [],

            "candidate_count": 0,

            "candidates_examined": 0,

            "stopped_after_limit": False,

            "requested_ingredients": requested,

        }

    connection = get_connection()

    try:

        # ------------------------------------------
        # Count all FTS candidate recipes
        # ------------------------------------------

        candidate_count = connection.execute(
            """
            SELECT COUNT(*)

            FROM recipes_fts

            JOIN recipes AS r

                ON recipes_fts.recipe_id = r.recipe_id

            WHERE recipes_fts MATCH ?

                AND r.has_title = 1

                AND r.has_ingredients = 1

            """,

            (fts_query,)

        ).fetchone()[0]

        # ------------------------------------------
        # Retrieve candidates in BM25 relevance order
        # ------------------------------------------

        cursor = connection.execute(
            """

            WITH candidates AS (

                SELECT

                    recipe_id,

                    bm25(
                        recipes_fts,
                        0.0,
                        10.0,
                        5.0,
                        1.0
                    ) AS relevance_score

                FROM recipes_fts

                WHERE recipes_fts MATCH ?

            )

            SELECT

                c.recipe_id,

                c.relevance_score,

                r.title_original,

                r.ingredients_original_json,

                r.instructions_original,

                r.source_file,

                ri.position,

                ri.ingredient_original,

                ri.is_searchable

            FROM candidates AS c

            JOIN recipes AS r

                ON c.recipe_id = r.recipe_id

            LEFT JOIN recipe_ingredients AS ri

                ON r.recipe_id = ri.recipe_id

            WHERE r.has_title = 1

                AND r.has_ingredients = 1

            ORDER BY

                c.relevance_score ASC,

                c.recipe_id ASC,

                ri.position ASC

            """,

            (fts_query,)

        )

        matched_results = []

        candidates_examined = 0

        current_candidate = None

        stopped_after_limit = False

        # ------------------------------------------
        # Finish processing one recipe candidate
        # ------------------------------------------

        def finish_candidate(candidate):

            nonlocal candidates_examined

            if candidate is None:

                return False

            candidates_examined += 1

            validated = validate_candidate(
                candidate,
                requested
            )

            if validated is not None:

                matched_results.append(validated)

            return len(matched_results) >= limit

        # ------------------------------------------
        # Process database rows in recipe groups
        # ------------------------------------------

        for row in cursor:

            recipe_id = row["recipe_id"]

            # First recipe.
            if current_candidate is None:

                current_candidate = create_candidate(row)

            # A new recipe ID means the previous
            # recipe's ingredient entries are complete.
            elif recipe_id != current_candidate["recipe_id"]:

                limit_reached = finish_candidate(
                    current_candidate
                )

                if limit_reached:

                    stopped_after_limit = True

                    break

                current_candidate = create_candidate(row)

            # Collect searchable ingredient evidence.
            if (

                row["ingredient_original"] is not None

                and row["is_searchable"]

            ):

                current_candidate[
                    "ingredient_entries"
                ].append(
                    row["ingredient_original"]
                )

        # ------------------------------------------
        # Process the final recipe
        # ------------------------------------------

        if not stopped_after_limit:

            finish_candidate(
                current_candidate
            )

        return {

            "results": matched_results,

            "candidate_count": candidate_count,

            "candidates_examined": candidates_examined,

            "stopped_after_limit": stopped_after_limit,

            "requested_ingredients": requested,

        }

    finally:

        connection.close()


# ==================================================
# 11. DISPLAY SEARCH RESULTS
# ==================================================

def display_results(output):

    print("\n" + "=" * 65)

    print("NOSH AI - INGREDIENT SEARCH")

    print("=" * 65)

    print(
        "Requested ingredients:",
        output["requested_ingredients"]
    )

    print(
        "Total FTS candidate recipes:",
        f"{output['candidate_count']:,}"
    )

    print(
        "Candidates checked:",
        f"{output['candidates_examined']:,}"
    )

    print(
        "Matching recipes returned:",
        len(output["results"])
    )

    if output["stopped_after_limit"]:

        print(
            "Search stopped after collecting the "
            "requested number of highest-ranked matches."
        )

    results = output["results"]

    if not results:

        print("\nNo verified matching recipes found.")

        return

    for index, recipe in enumerate(
        results,
        start=1
    ):

        print("\n" + "-" * 65)

        print(f"RESULT {index}")

        print("-" * 65)

        print("Title:", recipe["title"])

        print("Recipe ID:", recipe["recipe_id"])

        print("Source:", recipe["source_file"])

        print("\nVerified ingredient evidence:")

        for requested, lines in (
            recipe["matched_ingredients"].items()
        ):

            print(f"\n{requested}:")

            for line in lines:

                print("  -", line)

        print("\nAll original ingredients:")

        for ingredient in recipe["ingredients"]:

            if isinstance(ingredient, str):

                print(" -", ingredient)

        print(
            "\nBM25 relevance score:",
            round(recipe["relevance_score"], 5)
        )


# ==================================================
# 12. COMMAND LINE INTERFACE
# ==================================================

def main():

    parser = argparse.ArgumentParser(
        description="Search recipes by verified ingredients."
    )

    parser.add_argument(
        "--ingredient",
        nargs="+",
        required=True,
        help="One or more required ingredients."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recipes to return."
    )

    args = parser.parse_args()

    output = search_by_ingredients(
        ingredients=args.ingredient,
        limit=args.limit
    )

    display_results(output)


if __name__ == "__main__":

    main()
