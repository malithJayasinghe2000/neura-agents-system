"""Integration tests. A package, so shared fixtures can be imported by name.

`console_fixtures.py` builds one populated merchant and is used by every console
screen's tests. Without this file it is not importable as
`tests.integration.console_fixtures`, and the alternative — a copy per test file
— is how the *second* tenant in an isolation assertion quietly stops being
populated and the assertion stops asserting anything (`console.md §6.4`).
"""
