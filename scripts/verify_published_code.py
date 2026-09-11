"""Execute the downloaded code and tests in AgentCore, never on the workstation."""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.tools import run_code  # noqa: E402


def main():
    directory = Path("artifacts/real-agent-tools")
    journal = json.loads((directory / "live-verification.json").read_text())
    assert journal.get("verified")
    task = journal["tasks"]["development"]
    assert task["status"] == "completed"
    files, hashes = {}, {}
    for name in ("implementation.py", "tests.py"):
        content = (directory / "development" / name).read_text()
        metadata = next(a for a in task["execution"]["artifacts"] if a["name"] == name)
        digest = hashlib.sha256(content.encode()).hexdigest()
        assert digest == metadata["sha256"]
        files[name], hashes[name] = content, digest
    program = (
        "files = "
        + repr(files)
        + """
from pathlib import Path
import subprocess, sys, importlib.util
folder = Path('/tmp/marketplace_output_check')
folder.mkdir(exist_ok=True)
for name, content in files.items():
    (folder / name).write_text(content)
result = subprocess.run(
    [sys.executable, 'tests.py'], cwd=folder,
    capture_output=True, text=True, timeout=20,
)
print('Published tests stdout:', result.stdout)
print('Published tests stderr:', result.stderr)
assert result.returncode == 0, 'Published test file failed'
spec = importlib.util.spec_from_file_location(
    'published_implementation', folder / 'implementation.py',
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
summarize = module.summarize_orders
assert summarize([]) == {}
assert summarize([
    {'sku': 'A', 'quantity': 2},
    {'sku': 'B', 'quantity': 1},
    {'sku': 'A', 'quantity': 3},
]) == {'A': 5, 'B': 1}
assert summarize([{'sku': 'A', 'quantity': 0}]) == {'A': 0}
invalid = [
    {'sku': 'A', 'quantity': True},
    {'sku': 'A', 'quantity': -1},
    {'sku': 'A', 'quantity': 1.5},
    {'sku': '', 'quantity': 1},
    {'sku': None, 'quantity': 1},
    {'sku': 'A'},
    None,
]
for row in invalid:
    try:
        summarize([row])
    except ValueError:
        pass
    else:
        raise AssertionError(f'Invalid row was accepted: {row!r}')
print('10 independent specification checks passed.')
"""
    )
    result = run_code(program)
    (directory / "published-code-verification.json").write_text(
        json.dumps(
            {
                "task_id": task["id"],
                "execution_id": task["execution"]["id"],
                "sha256": hashes,
                "sandbox_result": result,
            },
            indent=2,
        )
        + "\n"
    )
    assert result["exit_code"] == 0 and not result["is_error"], (
        result["stdout"] + result["stderr"]
    )
    print(result["stdout"])


if __name__ == "__main__":
    main()
