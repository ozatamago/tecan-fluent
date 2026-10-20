"""The error of the ODTC features (also used by Status for FluentControl's state)."""


class OdtcOperationFailed(Exception):
    """The ODTC operation could not be performed. The description explains why (FluentControl state, dialogs, ...)."""
