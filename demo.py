"""Runs the two assignment test inputs against the running API and saves the Word files.

Usage (server must already be running):
    python demo.py              # run both tests
    python demo.py standard     # only the standard request
    python demo.py complex      # only the complex request
"""
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"

TESTS = {
    "standard": "Create a project plan for launching a customer support chatbot for a retail company over 3 months.",
    "complex": (
        "We need something for the board about moving to the cloud, but the budget is tiny, we want it done "
        "by next month, and also fully secure and compliant. Not sure what format. Make it convincing."
    ),
}


def run(name: str, text: str) -> None:
    print("=" * 78)
    print(f"TEST: {name}\nREQUEST: {text}\n")
    response = httpx.post(f"{BASE_URL}/agent", json={"request": text}, timeout=600)
    if response.status_code != 200:
        print(f"FAILED ({response.status_code}): {response.text}")
        return

    body = response.json()
    plan = body["plan"]
    print(f"Document : {plan['title']}  [{plan['doc_type']}]  for {plan['audience']}")

    print("\nAssumptions the agent made:")
    for item in plan["assumptions"]:
        print(f"  - {item}")
    print("\nConflicts it detected and how it resolved them:")
    for item in plan["conflicts"] or []:
        print(f"  - {item['issue']}  ->  {item['resolution']}")
    if not plan["conflicts"]:
        print("  (none)")

    print("\nAgent-generated task list:")
    for task in plan["tasks"]:
        extra = f" ({task['data_type']})" if task["data_type"] else ""
        print(f"  {task['id']}. [{task['status'].upper():6}] {task['tool']}{extra}: {task['title']}")
        if task["error"]:
            print(f"       error: {task['error']}")

    reflection = body["reflection"]
    print(f"\nReflection verdict: {reflection['verdict']}")
    for issue in reflection["issues"]:
        print(f"  - issue in '{issue['section'] or 'missing section'}': {issue['problem']}")
    print(f"  revised: {reflection['sections_revised']}  added: {reflection['sections_added']}")

    print(f"\n{body['message']}  ({body['duration_seconds']}s)")
    document = httpx.get(BASE_URL + body["download_url"], timeout=60)
    target = Path("outputs")
    target.mkdir(exist_ok=True)
    path = target / f"demo_{name}.docx"
    path.write_bytes(document.content)
    print(f"Saved Word document: {path.resolve()}")


if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "all"
    for key, value in TESTS.items():
        if choice in ("all", key):
            run(key, value)
