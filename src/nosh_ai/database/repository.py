
import argparse
import json
import sqlite3

from pathlib import Path


# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "recipes.db"
)


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
# 3. GET RECIPE USING ITS ID
# ==========================================

def get_recipe_by_id(recipe_id):

    """
    Retrieve one exact recipe using its original ID.
    """

    if not isinstance(recipe_id, str) or not recipe_id.strip():

        raise ValueError("Recipe ID cannot be empty.")

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT *

            FROM recipes

            WHERE recipe_id = ?

            """,
            (recipe_id.strip(),)

        ).fetchone()

        if row is None:

            return None

        recipe = dict(row)

        # Decode original ingredient JSON.
        if recipe["ingredients_original_json"] is not None:

            recipe["ingredients"] = json.loads(
                recipe["ingredients_original_json"]
            )

        else:

            recipe["ingredients"] = None

        return recipe

    finally:

        connection.close()


# ==========================================
# 4. GET NORMALIZED INGREDIENT ENTRIES
# ==========================================

def get_ingredient_entries(recipe_id):

    """
    Retrieve individual ingredient records
    belonging to a recipe.
    """

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT

                position,

                ingredient_original,

                ingredient_normalized,

                is_advertisement,

                is_searchable

            FROM recipe_ingredients

            WHERE recipe_id = ?

            ORDER BY position

            """,
            (recipe_id,)

        ).fetchall()

        return [dict(row) for row in rows]

    finally:

        connection.close()


# ==========================================
# 5. DISPLAY RECIPE DETAILS
# ==========================================

def display_recipe(recipe):

    print("\n" + "=" * 65)

    print("NOSH AI - RECIPE DETAILS")

    print("=" * 65)

    print("\nRecipe ID:")
    print(recipe["recipe_id"])

    print("\nTitle:")
    print(
        recipe["title_original"]
        if recipe["title_original"]
        else "Unavailable in dataset"
    )

    print("\nSource:")
    print(recipe["source_file"])

    print("\nIngredients:")

    ingredients = recipe["ingredients"]

    if ingredients:

        for ingredient in ingredients:

            if isinstance(ingredient, str):
                print(" -", ingredient)

    else:

        print("Ingredient information unavailable.")

    print("\nInstructions:")

    instructions = recipe["instructions_original"]

    if instructions and instructions.strip():

        print(instructions)

    else:

        print("Instructions unavailable in dataset.")

    print("\nData completeness:")

    print("Has title:", bool(recipe["has_title"]))

    print("Has ingredients:", bool(recipe["has_ingredients"]))

    print("Has instructions:", bool(recipe["has_instructions"]))

    print("Complete recipe:", bool(recipe["is_complete"]))

    print("\n" + "=" * 65)


# ==========================================
# 6. COMMAND LINE INTERFACE
# ==========================================

def main():

    parser = argparse.ArgumentParser(
        description="Retrieve an exact Nosh AI recipe."
    )

    parser.add_argument(
        "--recipe-id",
        required=True,
        help="Original recipe ID."
    )

    args = parser.parse_args()

    recipe = get_recipe_by_id(args.recipe_id)

    if recipe is None:

        print("\nNo recipe found with that ID.")

        return

    display_recipe(recipe)


if __name__ == "__main__":

    main()
