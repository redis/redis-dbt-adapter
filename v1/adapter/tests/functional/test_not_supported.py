"""General privileges are intentionally narrower than dbt's generic suite.

Executable scoped native SELECT replacements live in
../integration/test_native_select_contract.py, including negative privilege,
role and view cases. CI provisions dedicated roles and runs that file serially.
"""
