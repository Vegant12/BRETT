"""Third-party provider integrations.

Each subpackage owns ALL request/response code for one provider (HEVY-05). Nothing outside a
provider package may import that package's wire schemas -- enforced by
``backend/tests/test_hevy_isolation.py``.
"""
