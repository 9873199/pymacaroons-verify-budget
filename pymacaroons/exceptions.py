class MacaroonException(Exception):
    pass


class MacaroonInitException(MacaroonException):
    pass


class MacaroonVerificationFailedException(MacaroonException):
    pass


class MacaroonInvalidSignatureException(MacaroonVerificationFailedException):
    pass


class MacaroonUnmetCaveatException(MacaroonVerificationFailedException):
    pass


class MacaroonBudgetExceededException(MacaroonVerificationFailedException):
    """Raised when a verification exceeds its depth or attempt budget.

    This is a terminal failure: once a numeric limit is reached the run stops
    immediately and no further business caveat callbacks are invoked. The
    budget is shared across every branch of a single ``verify`` call, so work
    spent on a branch that is later backtracked out of is not refunded.
    """
    pass


class MacaroonDischargeCycleException(MacaroonVerificationFailedException):
    """Raised when a third-party discharge chain re-enters a candidate that is
    already on the current recursion path.

    A cycle only dooms the branch it occurs on: other candidates sharing the
    same identifier are still tried. The attempt spent entering the cyclic
    candidate is never refunded, so a cycle cannot be used to dodge the
    attempt budget.
    """
    pass


class MacaroonSerializationException(MacaroonException):
    pass


class MacaroonDeserializationException(MacaroonException):
    pass
