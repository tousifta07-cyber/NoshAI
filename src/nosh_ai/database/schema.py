
import sqlite3
from pathlib import Path


# ==========================================
# 1. PROJECT CONFIGURATION
# ==========================================

# Find the main NoshAI project directory
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Database location
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

    """
    Connect to the SQLite database.

    If the database does not exist,
    SQLite will create it automatically.
    """

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    # Return database rows as dictionary-like objects
    connection.row_factory = sqlite3.Row

    # Enable foreign key relationships
    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    # Enable safer concurrent database access
    connection.execute(
        "PRAGMA journal_mode = WAL"
    )

    return connection


# ==========================================
# 3. CREATE DATABASE TABLES
# ==========================================

def create_schema(connection):

    """
    Create all required tables and indexes.
    """

    connection.executescript("""

    -- ==================================
    -- TABLE 1: RECIPES
    -- ==================================

    CREATE TABLE IF NOT EXISTS recipes (

        recipe_id TEXT PRIMARY KEY,

        source_file TEXT NOT NULL,

        title_original TEXT,

        ingredients_original_json TEXT,

        instructions_original TEXT,

        picture_link TEXT,

        raw_json TEXT NOT NULL,

        has_title INTEGER NOT NULL DEFAULT 0,

        has_ingredients INTEGER NOT NULL DEFAULT 0,

        has_instructions INTEGER NOT NULL DEFAULT 0,

        is_complete INTEGER NOT NULL DEFAULT 0

    );


    -- ==================================
    -- TABLE 2: RECIPE INGREDIENTS
    -- ==================================

    CREATE TABLE IF NOT EXISTS recipe_ingredients (

        ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,

        recipe_id TEXT NOT NULL,

        position INTEGER NOT NULL,

        ingredient_original TEXT NOT NULL,

        ingredient_normalized TEXT NOT NULL DEFAULT '',

        is_advertisement INTEGER NOT NULL DEFAULT 0,

        is_searchable INTEGER NOT NULL DEFAULT 1,

        FOREIGN KEY (recipe_id)
            REFERENCES recipes(recipe_id)
            ON DELETE CASCADE,

        UNIQUE(recipe_id, position)

    );


    -- ==================================
    -- TABLE 3: INGREDIENT ALIASES
    -- ==================================

    CREATE TABLE IF NOT EXISTS ingredient_aliases (

        alias_normalized TEXT PRIMARY KEY,

        canonical_name TEXT NOT NULL,

        notes TEXT

    );


    -- ==================================
    -- TABLE 4: FULL TEXT SEARCH
    -- ==================================

    CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts

    USING fts5(

        recipe_id UNINDEXED,

        title,

        ingredients,

        instructions,

        tokenize = 'unicode61 remove_diacritics 2'

    );


    -- ==================================
    -- TABLE 5: INGESTION METADATA
    -- ==================================

    CREATE TABLE IF NOT EXISTS ingestion_metadata (

        metadata_key TEXT PRIMARY KEY,

        metadata_value TEXT NOT NULL

    );


    -- ==================================
    -- CREATE INDEXES
    -- ==================================

    CREATE INDEX IF NOT EXISTS idx_recipes_source
    ON recipes(source_file);


    CREATE INDEX IF NOT EXISTS idx_recipes_title
    ON recipes(title_original);


    CREATE INDEX IF NOT EXISTS idx_ingredients_recipe
    ON recipe_ingredients(recipe_id);


    CREATE INDEX IF NOT EXISTS idx_ingredients_normalized
    ON recipe_ingredients(ingredient_normalized);


    CREATE INDEX IF NOT EXISTS idx_ingredients_searchable
    ON recipe_ingredients(is_searchable);


    """)

    # Set database schema version
    connection.execute(
        "PRAGMA user_version = 1"
    )

    connection.commit()


# ==========================================
# 4. VERIFY DATABASE TABLES
# ==========================================

def verify_schema(connection):

    expected_tables = [
        "recipes",
        "recipe_ingredients",
        "ingredient_aliases",
        "recipes_fts",
        "ingestion_metadata"
    ]

    print("\nDATABASE SCHEMA VERIFICATION")
    print("=" * 50)

    for table in expected_tables:

        result = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE name = ?
            """,
            (table,)
        ).fetchone()

        if result:
            print(f"[OK] {table}")

        else:
            print(f"[MISSING] {table}")

    # Check the current schema version
    version = connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0]

    print("\nDatabase version:", version)

    # Verify that database is initially empty
    recipe_count = connection.execute(
        "SELECT COUNT(*) FROM recipes"
    ).fetchone()[0]

    print("Currently imported recipes:", recipe_count)


# ==========================================
# 5. MAIN FUNCTION
# ==========================================

def main():

    print("Creating Nosh AI database...")

    connection = get_connection()

    try:

        create_schema(connection)

        verify_schema(connection)

        print("\nDatabase created successfully!")

        print("Database location:")
        print(DB_PATH)

    except sqlite3.Error as error:

        print("\nDatabase error:", error)

        raise

    finally:

        connection.close()


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":
    main()
