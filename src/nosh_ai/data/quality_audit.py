
import json
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATASET_DIR = PROJECT_ROOT / "data" / "raw" / "extracted"
REPORT_DIR = PROJECT_ROOT / "data" / "processed"

JSON_FILES = [
    "recipes_raw_nosource_ar.json",
    "recipes_raw_nosource_epi.json",
    "recipes_raw_nosource_fn.json",
]

MAX_EXAMPLES = 5


def inspect_records(file_path):

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Expected dictionary-based JSON.")

    issue_counts = Counter()
    issue_examples = []
    advertisement_records = 0
    standalone_ad_entries = 0
    total_ad_entries = 0

    for recipe_id, recipe in data.items():

        issues = []

        if not isinstance(recipe, dict):
            issue_counts["invalid_recipe_object"] += 1
            continue

        # Inspect title
        title = recipe.get("title")

        if "title" not in recipe:
            issues.append("missing_title")
        elif title is None:
            issues.append("null_title")
        elif not isinstance(title, str):
            issues.append("invalid_title_type")
        elif not title.strip():
            issues.append("empty_title")

        # Inspect ingredients
        ingredients = recipe.get("ingredients")

        if "ingredients" not in recipe:
            issues.append("missing_ingredients")

        elif ingredients is None:
            issues.append("null_ingredients")

        elif not isinstance(ingredients, list):
            issues.append("invalid_ingredients_type")

        elif len(ingredients) == 0:
            issues.append("empty_ingredients")

        else:
            non_string_count = sum(
                not isinstance(item, str)
                for item in ingredients
            )

            if non_string_count:
                issues.append("non_string_ingredients")

            ad_count = sum(
                isinstance(item, str)
                and "ADVERTISEMENT" in item.upper()
                for item in ingredients
            )

            standalone_count = sum(
                isinstance(item, str)
                and item.strip().upper() == "ADVERTISEMENT"
                for item in ingredients
            )

            if ad_count:
                advertisement_records += 1
                total_ad_entries += ad_count

            standalone_ad_entries += standalone_count

        # Inspect instructions
        instructions = recipe.get("instructions")

        if "instructions" not in recipe:
            issues.append("missing_instructions")
        elif instructions is None:
            issues.append("null_instructions")
        elif not isinstance(instructions, str):
            issues.append("invalid_instructions_type")
        elif not instructions.strip():
            issues.append("empty_instructions")

        for issue in issues:
            issue_counts[issue] += 1

        if issues and len(issue_examples) < MAX_EXAMPLES:
            issue_examples.append({
                "recipe_id": recipe_id,
                "issues": issues,
                "title": title,
                "ingredients": ingredients,
                "instructions": instructions,
            })

    return {
        "filename": file_path.name,
        "total_recipes": len(data),
        "issue_counts": dict(issue_counts),
        "records_with_advertisement": advertisement_records,
        "total_advertisement_entries": total_ad_entries,
        "standalone_advertisement_entries": standalone_ad_entries,
        "problematic_record_examples": issue_examples,
    }


def main():

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    reports = []

    for filename in JSON_FILES:

        file_path = DATASET_DIR / filename

        if not file_path.exists():
            raise FileNotFoundError(file_path)

        report = inspect_records(file_path)
        reports.append(report)

        print("\n" + "=" * 65)
        print(report["filename"])
        print("=" * 65)

        print("Total recipes:", report["total_recipes"])
        print("Issue counts:", report["issue_counts"])

        print(
            "Records with advertisement:",
            report["records_with_advertisement"]
        )

        print(
            "Standalone advertisement entries:",
            report["standalone_advertisement_entries"]
        )

        print("\nPROBLEMATIC RECORD EXAMPLES:")

        for example in report["problematic_record_examples"]:
            print(json.dumps(
                example,
                indent=2,
                ensure_ascii=False
            ))

    output = {
        "files_audited": len(reports),
        "file_reports": reports,
    }

    output_path = REPORT_DIR / "data_quality_report.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\n" + "=" * 65)
    print("QUALITY AUDIT COMPLETED")
    print("=" * 65)
    print("Report saved to:", output_path)


if __name__ == "__main__":
    main()
