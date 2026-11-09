
import json
from pathlib import Path
from collections import Counter, defaultdict

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATASET_DIR = PROJECT_ROOT / "data" / "raw" / "extracted"
REPORT_DIR = PROJECT_ROOT / "data" / "processed"

JSON_FILES = [
    "recipes_raw_nosource_ar.json",
    "recipes_raw_nosource_epi.json",
    "recipes_raw_nosource_fn.json",
]

REQUIRED_FIELDS = [
    "title",
    "ingredients",
    "instructions",
]


def get_recipe_records(data):
    """
    Support both dictionary-based and list-based JSON structures.
    The current dataset preview suggests a dictionary keyed by recipe ID.
    """

    if isinstance(data, dict):
        yield from data.items()

    elif isinstance(data, list):
        for index, recipe in enumerate(data):
            recipe_id = None

            if isinstance(recipe, dict):
                recipe_id = recipe.get("id")

            if recipe_id is None:
                recipe_id = f"record_{index}"

            yield str(recipe_id), recipe

    else:
        raise ValueError(
            f"Unsupported JSON root type: {type(data).__name__}"
        )


def preview(value, limit=180):
    """Return a short, readable preview of a value."""

    if isinstance(value, str):
        return value[:limit]

    return value


def inspect_file(file_path, global_ids):
    print("\n" + "=" * 75)
    print(f"INSPECTING: {file_path.name}")
    print("=" * 75)

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    root_type = type(data).__name__

    print(f"Root JSON type: {root_type}")

    field_counts = Counter()
    missing_fields = Counter()
    null_fields = Counter()
    empty_fields = Counter()

    non_dictionary_records = 0
    invalid_ingredient_lists = 0
    non_string_ingredients = 0
    non_string_instructions = 0

    ingredient_counts = []
    recipe_ids = []

    sample_id = None
    sample_recipe = None

    record_count = 0

    for recipe_id, recipe in get_recipe_records(data):

        record_count += 1
        recipe_ids.append(recipe_id)

        if root_type == "dict":
            global_ids[recipe_id].append(file_path.name)

        if sample_recipe is None:
            sample_id = recipe_id
            sample_recipe = recipe

        if not isinstance(recipe, dict):
            non_dictionary_records += 1

            for field in REQUIRED_FIELDS:
                missing_fields[field] += 1

            continue

        for field in recipe:
            field_counts[field] += 1

        for field in REQUIRED_FIELDS:

            if field not in recipe:
                missing_fields[field] += 1
                continue

            value = recipe[field]

            if value is None:
                null_fields[field] += 1

            if value == "" or value == []:
                empty_fields[field] += 1

        ingredients = recipe.get("ingredients")

        if isinstance(ingredients, list):

            ingredient_counts.append(len(ingredients))

            for ingredient in ingredients:
                if not isinstance(ingredient, str):
                    non_string_ingredients += 1

        else:
            invalid_ingredient_lists += 1

        instructions = recipe.get("instructions")

        if instructions is not None and not isinstance(
            instructions, str
        ):
            non_string_instructions += 1

    # Sample recipe details
    sample_details = None

    if isinstance(sample_recipe, dict):
        sample_details = {
            "recipe_id": sample_id,
            "available_fields": list(sample_recipe.keys()),
            "title": preview(sample_recipe.get("title")),
            "ingredients_type": type(
                sample_recipe.get("ingredients")
            ).__name__,
            "ingredient_count": (
                len(sample_recipe["ingredients"])
                if isinstance(sample_recipe.get("ingredients"), list)
                else None
            ),
            "first_three_ingredients": (
                sample_recipe["ingredients"][:3]
                if isinstance(sample_recipe.get("ingredients"), list)
                else None
            ),
            "instructions_type": type(
                sample_recipe.get("instructions")
            ).__name__,
            "instructions_preview": preview(
                sample_recipe.get("instructions")
            ),
            "picture_link": sample_recipe.get("picture_link"),
        }

    summary = {
        "filename": file_path.name,
        "root_type": root_type,
        "record_count": record_count,
        "field_counts": dict(field_counts),
        "missing_fields": dict(missing_fields),
        "null_fields": dict(null_fields),
        "empty_fields": dict(empty_fields),
        "non_dictionary_records": non_dictionary_records,
        "invalid_ingredient_lists": invalid_ingredient_lists,
        "non_string_ingredients": non_string_ingredients,
        "non_string_instructions": non_string_instructions,
        "sample_recipe": sample_details,
    }

    print(f"Total recipes: {record_count:,}")
    print(f"Available fields: {dict(field_counts)}")
    print(f"Missing fields: {dict(missing_fields)}")
    print(f"Null fields: {dict(null_fields)}")
    print(f"Empty fields: {dict(empty_fields)}")
    print(f"Invalid ingredient lists: {invalid_ingredient_lists}")
    print(f"Non-string ingredient entries: {non_string_ingredients}")
    print(f"Non-string instructions: {non_string_instructions}")

    if ingredient_counts:
        print(
            f"Average ingredient entries: "
            f"{sum(ingredient_counts) / len(ingredient_counts):.2f}"
        )

    print("\nSAMPLE RECIPE:")
    print(json.dumps(sample_details, indent=4, ensure_ascii=False))

    return summary


def main():

    if not DATASET_DIR.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {DATASET_DIR}"
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    global_ids = defaultdict(list)
    all_summaries = []

    for filename in JSON_FILES:

        file_path = DATASET_DIR / filename

        if not file_path.exists():
            raise FileNotFoundError(
                f"Required dataset file missing: {file_path}"
            )

        summary = inspect_file(file_path, global_ids)
        all_summaries.append(summary)

    # Detect IDs shared between different source files.
    duplicate_ids = {
        recipe_id: sources
        for recipe_id, sources in global_ids.items()
        if len(sources) > 1
    }

    total_recipes = sum(
        item["record_count"] for item in all_summaries
    )

    report = {
        "dataset_directory": str(DATASET_DIR),
        "files_inspected": len(all_summaries),
        "total_recipes": total_recipes,
        "duplicate_ids_across_files": len(duplicate_ids),
        "duplicate_id_examples": dict(
            list(duplicate_ids.items())[:20]
        ),
        "file_summaries": all_summaries,
    }

    report_path = REPORT_DIR / "dataset_inspection_report.json"

    with report_path.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\n" + "=" * 75)
    print("DATASET INSPECTION COMPLETED")
    print("=" * 75)

    print(f"Files inspected: {len(all_summaries)}")
    print(f"Total recipes: {total_recipes:,}")
    print(f"Duplicate IDs across files: {len(duplicate_ids)}")
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
