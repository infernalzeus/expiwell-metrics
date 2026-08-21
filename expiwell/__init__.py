"""expiwell-metrics — ESM compliance and response metrics from ExpiWell exports.

Modules
-------
``parser``      reads the 4-row-preamble ExpiWell survey CSV into typed responses
``schedule``    the configured survey protocol (the compliance denominator)
``compliance``  response rates, timeliness and the PASS/REVIEW/FAIL verdict
``report``      multi-page PDF (summary, response calendar, timing)
"""

__version__ = "0.1.0"
