from pymacaroons.exceptions import (
    MacaroonBudgetExceededException,
    MacaroonDischargeCycleException,
)


class VerificationContext(object):
    """Depth and candidate-attempt budget for a single ``verify`` call.

    A fresh context is created for every root verification, so the branches of
    one verification share a budget while separate verifications (and separate
    ``Verifier`` instances) never affect each other.

    Depth counts the root macaroon as 0; each third-party discharge entered
    adds one. Attempts count each candidate whose verification actually
    starts, and are never refunded when a branch is backtracked out of.
    """

    def __init__(self, max_depth=None, max_attempts=None):
        self.max_depth = max_depth
        self.max_attempts = max_attempts
        self.depth = 0
        self.attempts = 0
        # Identities of the discharges on the current recursion path only.
        # Each identity pairs the concrete candidate macaroon with this
        # context, so neither a bare identifier nor a location is enough to
        # pronounce a cycle (distinct candidates sharing an identifier must
        # still each be tried).
        self._path = []

    def _identity(self, candidate):
        return (id(self), id(candidate))

    def enter_discharge(self, candidate):
        identity = self._identity(candidate)
        if identity in self._path:
            # Re-entering a candidate already on this path is a cycle. It only
            # invalidates the current branch; the caller backtracks and may
            # try other candidates. Nothing is charged, because this entry
            # never actually starts a verification.
            raise MacaroonDischargeCycleException(
                'Third-party discharge chain contains a cycle at depth '
                '{}'.format(self.depth + 1)
            )

        next_depth = self.depth + 1
        if self.max_depth is not None and next_depth > self.max_depth:
            raise MacaroonBudgetExceededException(
                'Maximum third-party discharge depth of {} exceeded'
                .format(self.max_depth)
            )

        next_attempts = self.attempts + 1
        if self.max_attempts is not None and next_attempts > self.max_attempts:
            raise MacaroonBudgetExceededException(
                'Maximum discharge candidate attempt budget of {} exceeded'
                .format(self.max_attempts)
            )

        self.depth = next_depth
        self.attempts = next_attempts
        self._path.append(identity)

    def exit_discharge(self, candidate):
        # Leaving a branch returns its depth slot and path position, but the
        # attempt stays spent: backtracking must not refund failed work.
        self._path.remove(self._identity(candidate))
        self.depth -= 1
