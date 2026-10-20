"""Create the private study template using the installed Vast CLI."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys


FOLDER = Path(__file__).resolve().parent


def command():
    template = json.loads((FOLDER / "template.json").read_text())
    operators = {"eq": "=", "gte": ">="}
    filters = []
    for field, comparison in template["extra_filters"].items():
        for operator, value in comparison.items():
            # The CLI accepts RAM in GB; the API payload stores MB.
            if field == "cpu_ram":
                value /= 1000
            value = str(value).lower() if isinstance(value, bool) else str(value).replace(" ", "_")
            filters.append(field + operators[operator] + value)
    arguments = ["vastai", "create", "template", "--ssh", "--direct", "--retry", "1"]
    for field, flag in (("name", "--name"), ("image", "--image"), ("tag", "--image_tag"),
                        ("env", "--env"), ("recommended_disk_space", "--disk_space"),
                        ("desc", "--desc"), ("readme", "--readme")):
        arguments.extend([flag, str(template[field])])
    arguments.extend(["--onstart-cmd", (FOLDER / "onstart.sh").read_text(),
                      "--search_params", " ".join(filters)])
    if not template["private"]:
        raise ValueError("This command creates private templates only.")
    return arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the command without contacting Vast")
    args = parser.parse_args()
    arguments = command()
    if args.dry_run:
        print(shlex.join(arguments))
        return 0
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=45)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    # Some CLI versions return zero even when the API request fails.
    return 0 if result.returncode == 0 and "New Template:" in result.stdout else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
