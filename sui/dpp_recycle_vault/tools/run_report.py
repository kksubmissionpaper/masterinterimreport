"""Run `sui move test separation` and print a readable result table.

PASS on a test marked expected_failure means: the call was REJECTED with the
expected abort code. This script labels each test accordingly.

Run from anywhere:  python tools/run_report.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = (ROOT / 'tests' / 'separation_tests.move').read_text(encoding='utf-8')

# test name -> expected abort-code name (None = success expected)
expected = {}
for m in re.finditer(
        r'#\[test(?:,\s*expected_failure\(abort_code\s*=\s*\w+::(\w+)\))?\]\s*fun\s+(\w+)',
        TESTS):
    expected[m.group(2)] = m.group(1)

proc = subprocess.run(['sui', 'move', 'test', 'separation'], cwd=ROOT,
                      capture_output=True, text=True, encoding='utf-8')
out = proc.stdout + proc.stderr

rows, rejected, accepted, failed = [], 0, 0, 0
for line in out.splitlines():
    m = re.match(r'\[\s*(PASS|FAIL)\s*\]\s+\S+::(\w+)\s*$', line)
    if not m:
        continue
    status, name = m.groups()
    code = expected.get(name)
    if status == 'FAIL':
        failed += 1
        label = 'FAIL'
    elif code:
        rejected += 1
        label = f'PASS - REJECTED ({code})'
    else:
        accepted += 1
        label = 'PASS - ACCEPTED'
    rows.append((label, name))

if not rows:
    print(out)
    sys.exit('No test results found (build error?). Raw output above.')

w = max(len(r[0]) for r in rows)
for label, name in rows:
    print(f'{label:<{w}}  {name}')
print(f'\n{accepted} accepted as expected, {rejected} rejected as expected, {failed} failed')
sys.exit(1 if failed else 0)
