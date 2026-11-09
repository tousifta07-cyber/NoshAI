
import argparse
import ijson
import json
import re
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path


# ==================================================
# 1. PROJECT CONFIGURATION
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATASET_DIR = PROJECT_ROOT / "data" / "raw" / "extracted"

DB_PATH = PROJECT_ROOT / "data" / "processed" / "recipes.db"

REPORT_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "ingestion_report.json"
)

JSON_FILES = [
    "recipes_raw_nosource_ar.json",
    "recipes_raw_nosource_epi.json",
    "recipes_raw_nosource_fn.json",
]

# Counts verified during our earlier dataset audit.
EXPECTED_COUNTS = {
    "recipes_raw_nosource_ar.json": 39802,
    "recipes_raw_nosource_epi.json": 25323,
    "recipes_raw_nosource_fn.json": 60039,
}

BATCH_SIZE = 500

ADVERTISEMENT_PATTERN = re.compile(
    r"\bADVERTISEMENT\b",
    flags=re.IGNORECASE
)

WHITESPACE_PATTERN = re.compile(r"\s+")


# ==================================================
# 2. TEXT NORMALIZATION
# ==================================================

def normalize_search_text(text):
    """
    Clean a separate searchable copy of text.

    Original recipe information is never modified.
    """

    if not isinstance(text, str):
        return ""

    # Remove advertisement markers.
    text = ADVERTISEMENT_PATTERN.sub(" ", text)

    # Replace repeated spaces and newlines.
    text = WHITESPACE_PATTERN.sub(" ", text)

    # Remove leading/trailing spaces and lowercase.
    return text.strip().casefold()


def normalize_ingredient(ingredient):
    """
    Normalize an ingredient for searching and matching.
    """

    return normalize_search_text(ingredient)


# ==================================================
# 3. DATABASE CONNECTION
# ==================================================

def get_connection():

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        DB_PATH,
        timeout=60
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")

    return connection


# ==================================================
# 4. PREPARE ONE RECIPE
# ==================================================

def prepare_recipe(recipe_id, recipe, source_file):

    """
    Convert one original JSON record into database rows.

    Returns:
        recipe_row
        ingredient_rows
        fts_row
        invalid_ingredient_count
    """

    if not isinstance(recipe, dict):

        recipe_data = {}

    else:

        recipe_data = recipe

    # ----------------------------------------------
    # Preserve original values
    # ----------------------------------------------

    title = recipe_data.get("title")

    ingredients = recipe_data.get("ingredients")

    instructions = recipe_data.get("instructions")

    picture_link = recipe_data.get("picture_link")

    # Save the original ingredient list as JSON.
    ingredients_original_json = None

    if "ingredients" in recipe_data:

        ingredients_original_json = json.dumps(
            ingredients,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str
        )

    # Preserve the complete original recipe object.
    raw_json = json.dumps(
        recipe,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str
    )

    # ----------------------------------------------
    # Validate required fields
    # ----------------------------------------------

    has_title = (
        isinstance(title, str)
        and bool(title.strip())
    )

    has_instructions = (
        isinstance(instructions, str)
        and bool(instructions.strip())
    )

    # ----------------------------------------------
    # Prepare searchable ingredients
    # ----------------------------------------------

    ingredient_rows = []

    normalized_ingredients = []

    invalid_ingredient_count = 0

    has_usable_ingredients = False

    if isinstance(ingredients, list):

        for position, ingredient in enumerate(ingredients):

            # Preserve unusual values in raw_json,
            # but only index string ingredients.
            if not isinstance(ingredient, str):

                invalid_ingredient_count += 1
                continue

            normalized = normalize_ingredient(ingredient)

            contains_advertisement = bool(
                ADVERTISEMENT_PATTERN.search(ingredient)
            )

            is_searchable = bool(normalized)

            if is_searchable:

                has_usable_ingredients = True

                normalized_ingredients.append(normalized)

            ingredient_rows.append((
                recipe_id,
                position,
                ingredient,
                normalized,
                int(contains_advertisement),
                int(is_searchable)
            ))

    has_ingredients = has_usable_ingredients

    is_complete = (
        has_title
        and has_ingredients
        and has_instructions
    )

    # ----------------------------------------------
    # Build main recipe row
    # ----------------------------------------------

    recipe_row = (
        recipe_id,
        source_file,
        title if isinstance(title, str) else None,
        ingredients_original_json,
        instructions if isinstance(instructions, str) else None,
        str(picture_link) if picture_link is not None else None,
        raw_json,
        int(has_title),
        int(has_ingredients),
        int(has_instructions),
        int(is_complete)
    )

    # ----------------------------------------------
    # Prepare FTS5 searchable text
    # ----------------------------------------------

    title_search = normalize_search_text(title)

    ingredients_search = " ".join(
        normalized_ingredients
    )

    instructions_search = normalize_search_text(
        instructions
    )

    fts_row = (
        recipe_id,
        title_search,
        ingredients_search,
        instructions_search
    )

    return (
        recipe_row,
        ingredient_rows,
        fts_row,
        invalid_ingredient_count
    )


# ==================================================
# 5. INSERT ONE BATCH INTO SQLITE
# ==================================================

def insert_batch(
    connection,
    recipe_batch,
    ingredient_batch,
    fts_batch
):

    """
    Insert recipe, ingredient and search records
    inside one database transaction.
    """

    if not recipe_batch:
        return

    with connection:

        connection.executemany(
            """
            INSERT INTO recipes (
                recipe_id,
                source_file,
                title_original,
                ingredients_original_json,
                instructions_original,
                picture_link,
                raw_json,
                has_title,
                has_ingredients,
                has_instructions,
                is_complete
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            recipe_batch
        )

        if ingredient_batch:

            connection.executemany(
                """
                INSERT INTO recipe_ingredients (
                    recipe_id,
                    position,
                    ingredient_original,
                    ingredient_normalized,
                    is_advertisement,
                    is_searchable
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ingredient_batch
            )

        connection.executemany(
            """
            INSERT INTO recipes_fts (
                recipe_id,
                title,
                ingredients,
                instructions
            )
            VALUES (?, ?, ?, ?)
            """,
            fts_batch
        )


# ==================================================
# 6. RESET EXISTING IMPORTED DATA
# ==================================================

def reset_database(connection):

    """
    Remove previously imported records.

    Ingredient aliases are kept because they may
    contain manually maintained mappings.
    """

    print("\nResetting existing recipe data...")

    with connection:

        connection.execute(
            "DELETE FROM recipes_fts"
        )

        connection.execute(
            "DELETE FROM recipe_ingredients"
        )

        connection.execute(
            "DELETE FROM recipes"
        )

        connection.execute(
            "DELETE FROM ingestion_metadata"
        )

    print("Existing recipe data cleared.")


# ==================================================
# 7. IMPORT ALL JSON FILES
# ==================================================

def import_dataset(connection):

    start_time = time.perf_counter()

    started_at = datetime.now(
        timezone.utc
    ).isoformat()

    recipe_batch = []

    ingredient_batch = []

    fts_batch = []

    source_counts = {}

    total_imported = 0

    invalid_ingredient_count = 0

    print("\nSTARTING DATA INGESTION")
    print("=" * 60)

    for filename in JSON_FILES:

        file_path = DATASET_DIR / filename

        if not file_path.exists():

            raise FileNotFoundError(
                f"Dataset file not found: {file_path}"
            )

        print(f"\nProcessing: {filename}")

        file_count = 0

        # Open JSON in binary mode for ijson.
        with file_path.open("rb") as file:

            # Each root dictionary key is a recipe ID.
            for recipe_id, recipe in ijson.kvitems(
                file,
                "",
                use_float=True
            ):

                recipe_row, ingredient_rows, fts_row, invalid_count = (
                    prepare_recipe(
                        recipe_id,
                        recipe,
                        filename
                    )
                )

                recipe_batch.append(recipe_row)

                ingredient_batch.extend(ingredient_rows)

                fts_batch.append(fts_row)

                invalid_ingredient_count += invalid_count

                file_count += 1

                total_imported += 1

                # Save every 500 recipes.
                if len(recipe_batch) >= BATCH_SIZE:

                    insert_batch(
                        connection,
                        recipe_batch,
                        ingredient_batch,
                        fts_batch
                    )

                    recipe_batch.clear()
                    ingredient_batch.clear()
                    fts_batch.clear()

                # Display progress.
                if file_count % 5000 == 0:

                    print(
                        f"  Imported {file_count:,} recipes..."
                    )

        # Save the remaining records from this file.
        if recipe_batch:

            insert_batch(
                connection,
                recipe_batch,
                ingredient_batch,
                fts_batch
            )

            recipe_batch.clear()
            ingredient_batch.clear()
            fts_batch.clear()

        source_counts[filename] = file_count

        print(
            f"Completed {filename}: {file_count:,} recipes"
        )

    elapsed_seconds = round(
        time.perf_counter() - start_time,
        2
    )

    completed_at = datetime.now(
        timezone.utc
    ).isoformat()

    # ----------------------------------------------
    # Verify imported database counts
    # ----------------------------------------------

    recipe_count = connection.execute(
        "SELECT COUNT(*) FROM recipes"
    ).fetchone()[0]

    ingredient_count = connection.execute(
        "SELECT COUNT(*) FROM recipe_ingredients"
    ).fetchone()[0]

    fts_count = connection.execute(
        "SELECT COUNT(*) FROM recipes_fts"
    ).fetchone()[0]

    complete_count = connection.execute(
        "SELECT COUNT(*) FROM recipes WHERE is_complete = 1"
    ).fetchone()[0]

    expected_counts_match = all(
        source_counts.get(filename) == expected
        for filename, expected in EXPECTED_COUNTS.items()
    )

    # ----------------------------------------------
    # Save ingestion metadata
    # ----------------------------------------------

    metadata = {
        "ingestion_started_at": started_at,
        "ingestion_completed_at": completed_at,
        "total_recipes_imported": recipe_count,
        "source_counts_json": json.dumps(source_counts),
        "batch_size": BATCH_SIZE,
        "invalid_ingredient_entries_skipped": invalid_ingredient_count
    }

    with connection:

        for key, value in metadata.items():

            connection.execute(
                """
                INSERT OR REPLACE INTO ingestion_metadata (
                    metadata_key,
                    metadata_value
                )
                VALUES (?, ?)
                """,
                (key, str(value))
            )

    # ----------------------------------------------
    # Save a separate report
    # ----------------------------------------------

    report = {
        "total_recipes_imported": recipe_count,
        "total_ingredient_entries": ingredient_count,
        "total_fts_records": fts_count,
        "complete_recipes": complete_count,
        "incomplete_recipes": recipe_count - complete_count,
        "source_counts": source_counts,
        "expected_counts_match_audit": expected_counts_match,
        "invalid_ingredient_entries_skipped": invalid_ingredient_count,
        "batch_size": BATCH_SIZE,
        "duration_seconds": elapsed_seconds
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with REPORT_PATH.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False
        )

    # ----------------------------------------------
    # Final output
    # ----------------------------------------------

    print("\n" + "=" * 60)
    print("DATA INGESTION COMPLETED")
    print("=" * 60)

    print(f"Recipes imported: {recipe_count:,}")

    print(f"Ingredient entries: {ingredient_count:,}")

    print(f"FTS records: {fts_count:,}")

    print(f"Complete recipes: {complete_count:,}")

    print(
        f"Incomplete recipes: "
        f"{recipe_count - complete_count:,}"
    )

    print(
        "Invalid ingredient entries skipped:",
        invalid_ingredient_count
    )

    print(
        "Matches previous dataset audit:",
        expected_counts_match
    )

    print(
        f"Time taken: {elapsed_seconds} seconds"
    )

    print("\nDatabase:", DB_PATH)

    print("Report:", REPORT_PATH)

    if recipe_count != total_imported:
        raise RuntimeError(
            "Database recipe count does not match imported count."
        )

    if fts_count != recipe_count:
        raise RuntimeError(
            "FTS record count does not match recipe count."
        )


# ==================================================
# 8. MAIN FUNCTION
# ==================================================

def main():

    parser = argparse.ArgumentParser(
        description="Import Recipe Box dataset into Nosh AI SQLite database."
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing imported recipe records before importing."
    )

    args = parser.parse_args()

    if not DATASET_DIR.exists():

        raise FileNotFoundError(
            f"Dataset directory does not exist: {DATASET_DIR}"
        )

    connection = get_connection()

    try:

        existing_count = connection.execute(
            "SELECT COUNT(*) FROM recipes"
        ).fetchone()[0]

        if existing_count > 0 and not args.reset:

            print(
                f"\nDatabase already contains "
                f"{existing_count:,} recipes."
            )

            print(
                "To rebuild the imported data, run:"
            )

            print(
                "python src/nosh_ai/data/ingest.py --reset"
            )

            return 1

        if args.reset:

            reset_database(connection)

        import_dataset(connection)

        print("\nAll database verification checks passed!")

        return 0

    except Exception as error:

        print("\nINGESTION FAILED:", error)

        raise

    finally:

        connection.close()


if __name__ == "__main__":

    raise SystemExit(main())
