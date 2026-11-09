
import argparse
import json
import re
import sqlite3

from pathlib import Path


# ==========================================
# 1. PROJECT CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "recipes.db"
)

SEARCH_FIELDS = {
    "all": None,
    "title": "title",
    "ingredients": "ingredients",
    "instructions": "instructions",
}


# ==========================================
# 2. DATABASE CONNECTION
# ==========================================

def get_connection():

    if not DB_PATH.exists():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row

    return connection


# ==========================================
# 3. PREPARE SEARCH QUERY
# ==========================================

def prepare_search_query(query, search_in="all"):

    """
    Convert user input into a safe FTS5 query.

    All terms must match.

    Search can be restricted to a particular
    database column.
    """

    if search_in not in SEARCH_FIELDS:

        raise ValueError(
            f"Unsupported search mode: {search_in}"
        )

    if not isinstance(query, str):

        return ""

    words = re.findall(
        r"[a-zA-Z0-9]+",
        query.casefold()
    )

    if not words:

        return ""

    safe_terms = [
        f'"{word}"'
        for word in words
    ]

    expression = " AND ".join(safe_terms)

    field = SEARCH_FIELDS[search_in]

    if field:

        expression = (
            f"{field} : ({expression})"
        )

    return expression


# ==========================================
# 4. SEARCH RECIPES
# ==========================================

def search_recipes(
    query,
    limit=10,
    search_in="all"
):

    """
    Search original recipe records through FTS5.

    Returns actual recipe information from SQLite.
    """

    if not isinstance(limit, int) or not 1 <= limit <= 100:

        raise ValueError(
            "Limit must be between 1 and 100."
        )

    match_query = prepare_search_query(
        query,
        search_in
    )

    if not match_query:

        return []

    connection = get_connection()

    try:

        results = connection.execute(
            """
            SELECT

                r.recipe_id,

                r.title_original,

                r.ingredients_original_json,

                r.instructions_original,

                r.source_file,

                r.has_ingredients,

                r.has_instructions,

                bm25(
                    recipes_fts,
                    0.0,
                    10.0,
                    5.0,
                    1.0
                ) AS relevance_score

            FROM recipes_fts

            JOIN recipes AS r

                ON recipes_fts.recipe_id = r.recipe_id

            WHERE recipes_fts MATCH ?

                AND r.has_title = 1

            ORDER BY relevance_score ASC

            LIMIT ?

            """,

            (match_query, limit)

        ).fetchall()

        formatted_results = []

        for row in results:

            ingredients_json = (
                row["ingredients_original_json"]
            )

            if ingredients_json:

                ingredients = json.loads(
                    ingredients_json
                )

            else:

                ingredients = []

            formatted_results.append({

                "recipe_id": row["recipe_id"],

                "title": row["title_original"],

                "ingredients": ingredients,

                "instructions": (
                    row["instructions_original"]
                ),

                "source_file": row["source_file"],

                "has_ingredients": bool(
                    row["has_ingredients"]
                ),

                "has_instructions": bool(
                    row["has_instructions"]
                ),

                "relevance_score": row["relevance_score"]

            })

        return formatted_results

    finally:

        connection.close()


# ==========================================
# 5. DISPLAY RESULTS
# ==========================================

def display_results(query, results, search_in):

    print("\n" + "=" * 65)

    print("NOSH AI RECIPE SEARCH")

    print("=" * 65)

    print("Search query:", query)

    print("Search mode:", search_in)

    print("Results returned:", len(results))

    if not results:

        print("\nNo matching recipes found.")

        return

    for index, recipe in enumerate(results, start=1):

        print("\n" + "-" * 65)

        print(f"RESULT {index}")

        print("-" * 65)

        print("Title:", recipe["title"])

        print("Recipe ID:", recipe["recipe_id"])

        print("Source:", recipe["source_file"])

        print("\nIngredients:")

        if recipe["ingredients"]:

            for ingredient in recipe["ingredients"]:

                print(" -", ingredient)

        else:

            print("Ingredient information unavailable.")

        print("\nInstructions:")

        instructions = recipe["instructions"]

        if instructions:

            print(instructions[:700])

        else:

            print("Instructions unavailable.")

        print(
            "\nBM25 relevance score:",
            round(recipe["relevance_score"], 5)
        )


# ==========================================
# 6. COMMAND LINE INTERFACE
# ==========================================

def main():

    parser = argparse.ArgumentParser(
        description="Search recipes in Nosh AI."
    )

    parser.add_argument(
        "query",
        nargs="+",
        help="Recipe search terms."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recipes to return."
    )

    parser.add_argument(
        "--search-in",
        choices=["all", "title", "ingredients", "instructions"],
        default="all",
        help="Choose the recipe field to search."
    )

    args = parser.parse_args()

    query = " ".join(args.query)

    results = search_recipes(
        query=query,
        limit=args.limit,
        search_in=args.search_in
    )

    display_results(
        query=query,
        results=results,
        search_in=args.search_in
    )


if __name__ == "__main__":

    main()
