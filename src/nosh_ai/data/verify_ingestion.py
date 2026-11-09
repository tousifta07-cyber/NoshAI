
import json
import sqlite3
import ijson
import time

from pathlib import Path
from datetime import datetime, timezone


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
    / "verification_report.json"
)

BATCH_SIZE = 2000

JSON_FILES = {
    "recipes_raw_nosource_ar.json": 39802,
    "recipes_raw_nosource_epi.json": 25323,
    "recipes_raw_nosource_fn.json": 60039,
}


# ==================================================
# 2. DATABASE CONNECTION
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

    # Use disk-backed temporary storage.
    connection.execute("PRAGMA temp_store = FILE")

    return connection


# ==================================================
# 3. TEMPORARY VERIFICATION TABLE
# ==================================================

def create_verification_table(connection):

    connection.execute("""
        DROP TABLE IF EXISTS temp.source_verify
    """)

    connection.execute("""
        CREATE TEMP TABLE source_verify (

            recipe_id TEXT PRIMARY KEY,

            source_file TEXT NOT NULL,

            raw_json TEXT NOT NULL

        )
    """)

    connection.commit()


# ==================================================
# 4. VERIFY ONE SOURCE FILE
# ==================================================

def verify_source_file(
    connection,
    filename,
    expected_count
):

    start_time = time.perf_counter()

    file_path = DATASET_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    print("\n" + "=" * 65)
    print(f"VERIFYING: {filename}")
    print("=" * 65)

    # Clear previous source records.
    with connection:

        connection.execute(
            "DELETE FROM source_verify"
        )

    batch = []

    source_count = 0

    # ----------------------------------------------
    # Read source JSON incrementally
    # ----------------------------------------------

    with file_path.open("rb") as file:

        for recipe_id, recipe in ijson.kvitems(
            file,
            "",
            use_float=True
        ):

            original_json = json.dumps(
                recipe,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str
            )

            batch.append((
                recipe_id,
                filename,
                original_json
            ))

            source_count += 1

            # Insert every 2,000 records.
            if len(batch) >= BATCH_SIZE:

                with connection:

                    connection.executemany(
                        """
                        INSERT INTO source_verify (
                            recipe_id,
                            source_file,
                            raw_json
                        )
                        VALUES (?, ?, ?)
                        """,
                        batch
                    )

                batch.clear()

            # Display progress.
            if source_count % 10000 == 0:

                print(
                    f"  Staged {source_count:,} records..."
                )

    # Insert remaining records.
    if batch:

        with connection:

            connection.executemany(
                """
                INSERT INTO source_verify (
                    recipe_id,
                    source_file,
                    raw_json
                )
                VALUES (?, ?, ?)
                """,
                batch
            )

        batch.clear()

    # ----------------------------------------------
    # Count staged records
    # ----------------------------------------------

    staged_count = connection.execute(
        "SELECT COUNT(*) FROM source_verify"
    ).fetchone()[0]

    # ----------------------------------------------
    # Find missing records
    # ----------------------------------------------

    missing_records = connection.execute("""
        SELECT COUNT(*)

        FROM source_verify AS s

        LEFT JOIN recipes AS r
            ON s.recipe_id = r.recipe_id

        WHERE r.recipe_id IS NULL

    """).fetchone()[0]

    # ----------------------------------------------
    # Find unexpected extra records
    # ----------------------------------------------

    extra_records = connection.execute("""
        SELECT COUNT(*)

        FROM recipes AS r

        LEFT JOIN source_verify AS s
            ON r.recipe_id = s.recipe_id

        WHERE r.source_file = ?
          AND s.recipe_id IS NULL

    """, (filename,)).fetchone()[0]

    # ----------------------------------------------
    # Verify source file mapping
    # ----------------------------------------------

    source_mismatches = connection.execute("""
        SELECT COUNT(*)

        FROM source_verify AS s

        JOIN recipes AS r
            ON s.recipe_id = r.recipe_id

        WHERE s.source_file != r.source_file

    """).fetchone()[0]

    # ----------------------------------------------
    # Verify complete original recipe content
    # ----------------------------------------------

    content_mismatches = connection.execute("""
        SELECT COUNT(*)

        FROM source_verify AS s

        JOIN recipes AS r
            ON s.recipe_id = r.recipe_id

        WHERE s.raw_json != r.raw_json

    """).fetchone()[0]

    # ----------------------------------------------
    # Final source result
    # ----------------------------------------------

    passed = (
        source_count == expected_count
        and staged_count == expected_count
        and missing_records == 0
        and extra_records == 0
        and source_mismatches == 0
        and content_mismatches == 0
    )

    elapsed = round(
        time.perf_counter() - start_time,
        2
    )

    results = {
        "filename": filename,
        "expected_records": expected_count,
        "source_records": source_count,
        "staged_records": staged_count,
        "missing_records": missing_records,
        "extra_records": extra_records,
        "source_mismatches": source_mismatches,
        "content_mismatches": content_mismatches,
        "status": "PASS" if passed else "FAIL",
        "duration_seconds": elapsed
    }

    print(f"\nSource records: {source_count:,}")
    print(f"Staged records: {staged_count:,}")
    print(f"Missing records: {missing_records}")
    print(f"Extra records: {extra_records}")
    print(f"Source mismatches: {source_mismatches}")
    print(f"Content mismatches: {content_mismatches}")

    print(
        f"Verification time: {elapsed} seconds"
    )

    print(
        f"RESULT: {'PASS' if passed else 'FAIL'}"
    )

    return results


# ==================================================
# 5. VERIFY FTS5 SEARCH
# ==================================================

def verify_fts(connection, total_recipes):

    print("\n" + "=" * 65)
    print("VERIFYING FULL TEXT SEARCH")
    print("=" * 65)

    # Count FTS records.
    fts_count = connection.execute(
        "SELECT COUNT(*) FROM recipes_fts"
    ).fetchone()[0]

    print(f"FTS records: {fts_count:,}")

    # Test actual full-text search.
    search_results = connection.execute(
        """
        SELECT recipe_id

        FROM recipes_fts

        WHERE recipes_fts MATCH ?

        LIMIT 10
        """,
        ("chicken",)
    ).fetchall()

    search_working = len(search_results) > 0

    # Validate the sample recipe IDs.
    invalid_ids = 0

    for result in search_results:

        exists = connection.execute(
            """
            SELECT 1

            FROM recipes

            WHERE recipe_id = ?
            """,
            (result["recipe_id"],)
        ).fetchone()

        if exists is None:
            invalid_ids += 1

    print(
        "Sample chicken search results:",
        len(search_results)
    )

    print(
        "Invalid sampled FTS IDs:",
        invalid_ids
    )

    print(
        "FTS search working:",
        search_working
    )

    return {
        "fts_count": fts_count,
        "expected_fts_count": total_recipes,
        "sample_results": len(search_results),
        "search_working": search_working,
        "invalid_sample_ids": invalid_ids,
        "passed": (
            fts_count == total_recipes
            and search_working
            and invalid_ids == 0
        )
    }


# ==================================================
# 6. MAIN DATABASE VERIFICATION
# ==================================================

def main():

    overall_start = time.perf_counter()

    connection = get_connection()

    source_results = []

    try:

        print("=" * 65)
        print("NOSH AI DATABASE VERIFICATION")
        print("=" * 65)

        # ------------------------------------------
        # 1. Database quick integrity check
        # ------------------------------------------

        integrity = connection.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]

        print("\nSQLite quick check:", integrity)

        # Note:
        # The earlier full PRAGMA integrity_check
        # was already confirmed as "ok".

        # ------------------------------------------
        # 2. Foreign key verification
        # ------------------------------------------

        foreign_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print(
            "Foreign key errors:",
            len(foreign_errors)
        )

        # ------------------------------------------
        # 3. Total recipe count
        # ------------------------------------------

        total_recipes = connection.execute(
            "SELECT COUNT(*) FROM recipes"
        ).fetchone()[0]

        print(
            "\nTotal recipes:",
            f"{total_recipes:,}"
        )

        expected_total = sum(
            JSON_FILES.values()
        )

        # ------------------------------------------
        # 4. Ingredient count
        # ------------------------------------------

        ingredient_count = connection.execute(
            "SELECT COUNT(*) FROM recipe_ingredients"
        ).fetchone()[0]

        print(
            "Ingredient entries:",
            f"{ingredient_count:,}"
        )

        # ------------------------------------------
        # 5. Complete and incomplete recipes
        # ------------------------------------------

        complete = connection.execute(
            """
            SELECT COUNT(*)

            FROM recipes

            WHERE is_complete = 1
            """
        ).fetchone()[0]

        incomplete = connection.execute(
            """
            SELECT COUNT(*)

            FROM recipes

            WHERE is_complete = 0
            """
        ).fetchone()[0]

        print(
            "Complete recipes:",
            f"{complete:,}"
        )

        print(
            "Incomplete recipes:",
            f"{incomplete:,}"
        )

        # ------------------------------------------
        # 6. FTS5 verification
        # ------------------------------------------

        fts_results = verify_fts(
            connection,
            total_recipes
        )

        # ------------------------------------------
        # 7. Original source verification
        # ------------------------------------------

        create_verification_table(connection)

        print("\n" + "=" * 65)
        print("VERIFYING ORIGINAL SOURCE CONTENT")
        print("=" * 65)

        for filename, expected_count in JSON_FILES.items():

            result = verify_source_file(
                connection,
                filename,
                expected_count
            )

            source_results.append(result)

        source_checks_passed = all(
            result["status"] == "PASS"
            for result in source_results
        )

        # ------------------------------------------
        # 8. Final verification
        # ------------------------------------------

        final_passed = (
            integrity == "ok"
            and len(foreign_errors) == 0
            and total_recipes == expected_total
            and fts_results["passed"]
            and source_checks_passed
        )

        total_time = round(
            time.perf_counter() - overall_start,
            2
        )

        # ------------------------------------------
        # 9. Save verification report
        # ------------------------------------------

        report = {
            "verified_at": datetime.now(
                timezone.utc
            ).isoformat(),

            "database": str(DB_PATH),

            "integrity_check": integrity,

            "foreign_key_errors": len(
                foreign_errors
            ),

            "total_recipes": total_recipes,

            "expected_recipes": expected_total,

            "ingredient_entries": ingredient_count,

            "complete_recipes": complete,

            "incomplete_recipes": incomplete,

            "fts_results": fts_results,

            "source_verification": source_results,

            "total_verification_seconds": total_time,

            "final_status": (
                "PASS" if final_passed else "FAIL"
            )
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

        print("\n" + "=" * 65)

        print(
            "Total verification time:",
            total_time,
            "seconds"
        )

        if final_passed:

            print(
                "\nALL DATABASE VERIFICATION CHECKS PASSED!"
            )

        else:

            print(
                "\nDATABASE VERIFICATION FAILED."
            )

            raise RuntimeError(
                "One or more verification checks failed. "
                "Check the results above."
            )

        print("\nReport saved to:")
        print(REPORT_PATH)

    finally:

        connection.close()


# ==================================================
# 7. EXECUTION ENTRY POINT
# ==================================================

if __name__ == "__main__":

    main()
