from __future__ import unicode_literals

import pytest

from pymacaroons import Macaroon, Verifier
import pymacaroons.verifier as verifier_module
from pymacaroons.exceptions import (
    MacaroonBudgetExceededException,
    MacaroonDischargeCycleException,
    MacaroonInvalidSignatureException,
    MacaroonUnmetCaveatException,
)


def build_chain():
    """A root -> A -> B third-party chain, all discharges bound to root."""
    root = Macaroon(location='bank', identifier='root-id', key='root-key')
    root.add_third_party_caveat('A', 'a-key', 'a-id')

    a = Macaroon(location='A', identifier='a-id', key='a-key')
    a.add_first_party_caveat('a = ok')
    a.add_third_party_caveat('B', 'b-key', 'b-id')

    b = Macaroon(location='B', identifier='b-id', key='b-key')
    b.add_first_party_caveat('b = ok')

    return root, root.prepare_for_request(a), root.prepare_for_request(b)


def build_diamond():
    """root -> A; A has two third-party caveats (B and C) that are both
    discharged by a single macaroon D sharing one identifier."""
    root = Macaroon(location='', identifier='root', key='rk')
    root.add_third_party_caveat('A', 'ak', 'aid')

    a = Macaroon(location='A', identifier='aid', key='ak')
    a.add_third_party_caveat('B', 'bk', 'bid')
    a.add_third_party_caveat('C', 'ck', 'cid')

    b = Macaroon(location='B', identifier='bid', key='bk')
    b.add_third_party_caveat('D', 'dk', 'did')

    c = Macaroon(location='C', identifier='cid', key='ck')
    c.add_third_party_caveat('D', 'dk', 'did')

    d = Macaroon(location='D', identifier='did', key='dk')

    bound = [root.prepare_for_request(m) for m in (a, b, c, d)]
    return root, bound


def build_candidates(wrong_key='WRONG-key'):
    """A root caveat with two same-identifier discharge candidates:
    the first has the wrong key, the second is the valid one."""
    root = Macaroon(location='', identifier='root', key='rk')
    root.add_third_party_caveat('svc', 'real-key', 'xid')

    wrong = Macaroon(location='svc', identifier='xid', key=wrong_key)
    right = Macaroon(location='svc', identifier='xid', key='real-key')
    right.add_first_party_caveat('ok = yes')

    candidates = [root.prepare_for_request(wrong),
                  root.prepare_for_request(right)]
    return root, candidates


class CountingHmac(object):
    """Counts signature calculations actually started: one per
    verify_discharge entry (the root plus every discharge candidate)."""

    def __init__(self, monkeypatch):
        self.count = 0
        self._real = verifier_module.hmac_digest

        def counted(key, data):
            self.count += 1
            return self._real(key, data)

        monkeypatch.setattr(verifier_module, 'hmac_digest', counted)


def make_callback_counter(predicate):
    calls = {'n': 0}

    def callback(pred):
        calls['n'] += 1
        return pred == predicate

    return callback, calls


class TestVerificationBudget(object):

    def test_short_chain_passes_without_limits(self):
        root, a, b = build_chain()
        v = Verifier(discharge_macaroons=[a, b])
        v.satisfy_exact('a = ok')
        v.satisfy_exact('b = ok')

        assert v.verify(root, 'root-key') is True
        # Two discharges were entered; depth unwinds back to the root.
        assert v.verification_context.attempts == 2
        assert v.verification_context.depth == 0

    def test_depth_counts_root_as_zero(self):
        root, a, b = build_chain()

        v = Verifier(discharge_macaroons=[a, b])
        v.satisfy_exact('a = ok')
        v.satisfy_exact('b = ok')
        # A is depth 1, B is depth 2: a budget of exactly 2 completes.
        assert v.verify(root, 'root-key', max_depth=2) is True

        v2 = Verifier(discharge_macaroons=[a, b])
        v2.satisfy_exact('a = ok')
        v2.satisfy_exact('b = ok')
        # One more level than the budget allows trips the dedicated exception.
        with pytest.raises(MacaroonBudgetExceededException):
            v2.verify(root, 'root-key', max_depth=1)

    def test_diamond_reuses_one_discharge_across_separate_branches(self):
        root, bound = build_diamond()
        v = Verifier(discharge_macaroons=bound)

        assert v.verify(root, 'rk') is True
        # A, B, D, C, D: the same D object is entered on two *different*
        # recursion paths. A global seen-set would reject the second use; the
        # path-scoped guard allows it.
        assert v.verification_context.attempts == 5
        assert v.verification_context.depth == 0

    def test_wrong_candidate_then_right_candidate_is_found(self):
        root, candidates = build_candidates()

        v = Verifier(discharge_macaroons=candidates)
        v.satisfy_exact('ok = yes')
        # The first candidate fails its signature check, but the second (same
        # identifier) is still tried and discharges the caveat.
        assert v.verify(root, 'rk') is True
        assert v.verification_context.attempts == 2

    def test_attempt_budget_boundary_is_inclusive(self):
        root, candidates = build_candidates()

        exact = Verifier(discharge_macaroons=candidates)
        exact.satisfy_exact('ok = yes')
        # Both candidates are needed, so a budget of exactly 2 completes...
        assert exact.verify(root, 'rk', max_attempts=2) is True

        one_short = Verifier(discharge_macaroons=candidates)
        one_short.satisfy_exact('ok = yes')
        # ...while a single extra attempt beyond the budget raises.
        with pytest.raises(MacaroonBudgetExceededException):
            one_short.verify(root, 'rk', max_attempts=1)

    def test_failed_branch_attempts_are_not_refunded(self, monkeypatch):
        # root -> aid, with two A candidates (A1, A2); each needs bid, whose
        # two candidates both carry the wrong key. Backtracking over this tree
        # would explode if spent attempts were handed back.
        root = Macaroon(location='', identifier='root', key='rk')
        root.add_third_party_caveat('A', 'akey', 'aid')

        def make_a():
            a = Macaroon(location='A', identifier='aid', key='akey')
            a.add_first_party_caveat('a = ok')
            a.add_third_party_caveat('B', 'b-real', 'bid')
            return a

        a1, a2 = make_a(), make_a()
        b1 = Macaroon(location='B', identifier='bid', key='b-wrong-1')
        b2 = Macaroon(location='B', identifier='bid', key='b-wrong-2')
        bound = [root.prepare_for_request(m) for m in (a1, a2, b1, b2)]

        hmac = CountingHmac(monkeypatch)
        callback, calls = make_callback_counter('a = ok')

        v = Verifier(discharge_macaroons=bound)
        v.satisfy_general(callback)

        with pytest.raises(MacaroonBudgetExceededException):
            v.verify(root, 'rk', max_attempts=3)

        # Stopped precisely on the fourth entry attempt, before it started:
        # three candidates entered (A1, B1, B2), each costing one signature
        # calculation on top of the root's own calculation.
        assert v.verification_context.attempts == 3
        assert hmac.count == 4
        # Only A1's first-party caveat ran; once the budget tripped no further
        # business callbacks were invoked.
        assert calls['n'] == 1

    def test_unbounded_run_exhausts_every_combination_naturally(self,
                                                                monkeypatch):
        root = Macaroon(location='', identifier='root', key='rk')
        root.add_third_party_caveat('A', 'akey', 'aid')

        def make_a():
            a = Macaroon(location='A', identifier='aid', key='akey')
            a.add_first_party_caveat('a = ok')
            a.add_third_party_caveat('B', 'b-real', 'bid')
            return a

        a1, a2 = make_a(), make_a()
        b1 = Macaroon(location='B', identifier='bid', key='b-wrong-1')
        b2 = Macaroon(location='B', identifier='bid', key='b-wrong-2')
        bound = [root.prepare_for_request(m) for m in (a1, a2, b1, b2)]

        hmac = CountingHmac(monkeypatch)
        callback, calls = make_callback_counter('a = ok')

        v = Verifier(discharge_macaroons=bound)
        v.satisfy_general(callback)

        # No budget: all six candidate entries are paid for and the run ends
        # on the genuine signature failure, not a budget error or recursion.
        with pytest.raises(MacaroonInvalidSignatureException):
            v.verify(root, 'rk')
        assert v.verification_context.attempts == 6
        assert hmac.count == 7
        assert calls['n'] == 2

    def test_cycle_is_caught_by_path_identity_without_recursion(self):
        m1 = Macaroon(location='', identifier='root-id', key='root-key')
        m1.add_third_party_caveat(
            'bob', 'bob-caveat-root-key', 'bob-is-great')
        m2 = Macaroon(
            location='bob', identifier='bob-is-great',
            key='bob-caveat-root-key')
        # The discharge points back at the same identifier, so re-entering the
        # same candidate object forms a cycle.
        m2.add_third_party_caveat(
            'charlie', 'bob-caveat-root-key', 'bob-is-great')
        m2 = m1.prepare_for_request(m2)

        callback, calls = make_callback_counter('never')
        v = Verifier(discharge_macaroons=[m2])
        v.satisfy_general(callback)

        with pytest.raises(MacaroonDischargeCycleException):
            v.verify(m1, 'root-key')
        # The first entry was charged; the re-entrant second entry was refused
        # up front (and not charged), and no first-party business callback
        # ever ran.
        assert v.verification_context.attempts == 1
        assert calls['n'] == 0

    def test_distinct_candidates_sharing_identifier_are_not_collapsed(self):
        # Two genuinely different objects with one identifier: the cyclic one
        # only fails its own branch, so the valid sibling is still reached.
        # The identity is the candidate plus this verification, not the bare
        # identifier/location.
        root = Macaroon(location='', identifier='root', key='rk')
        root.add_third_party_caveat('svc', 'real-key', 'xid')

        cyclic = Macaroon(location='svc', identifier='xid', key='real-key')
        cyclic.add_third_party_caveat('svc', 'real-key', 'xid')
        valid = Macaroon(location='svc', identifier='xid', key='real-key')
        valid.add_first_party_caveat('ok = yes')

        candidates = [root.prepare_for_request(cyclic),
                      root.prepare_for_request(valid)]
        v = Verifier(discharge_macaroons=candidates)
        v.satisfy_exact('ok = yes')

        assert v.verify(root, 'rk') is True
        # Cyclic candidate entered once (its own re-entry is blocked, costing
        # nothing extra), the branch fails, then the distinct valid candidate
        # is entered fresh and succeeds.
        assert v.verification_context.attempts == 2

    def test_signature_and_root_binding_still_enforced_per_candidate(self):
        root = Macaroon(location='', identifier='root', key='rk')
        root.add_third_party_caveat('svc', 'real-key', 'xid')
        discharge = Macaroon(
            location='svc', identifier='xid', key='real-key')

        # Not bound to the root: the root-binding signature check must still
        # run and reject it, rather than any de-duplication shortcut accepting.
        v = Verifier(discharge_macaroons=[discharge])
        with pytest.raises(MacaroonInvalidSignatureException):
            v.verify(root, 'rk')

    def test_missing_discharge_still_raises_unmet_caveat(self):
        root = Macaroon(location='', identifier='root', key='rk')
        root.add_third_party_caveat('svc', 'real-key', 'xid')
        with pytest.raises(MacaroonUnmetCaveatException):
            Verifier().verify(root, 'rk')

    def test_budget_context_is_fresh_for_every_verify(self):
        root, candidates = build_candidates()

        v = Verifier(discharge_macaroons=candidates)
        v.satisfy_exact('ok = yes')
        with pytest.raises(MacaroonBudgetExceededException):
            v.verify(root, 'rk', max_attempts=1)
        assert v.verification_context.attempts == 1
        first_context = v.verification_context

        legal = Macaroon(location='', identifier='L', key='lk')
        legal.add_first_party_caveat('fine = true')
        v.satisfy_exact('fine = true')

        # Reusing the same Verifier rebuilds the context at zero, so a legal
        # token still verifies despite the earlier exhausted budget.
        assert v.verify(legal, 'lk') is True
        assert v.verification_context.attempts == 0
        assert v.verification_context is not first_context

    def test_separate_verifiers_do_not_share_budget(self):
        root, candidates = build_candidates()

        exhausted = Verifier(discharge_macaroons=candidates)
        exhausted.satisfy_exact('ok = yes')
        with pytest.raises(MacaroonBudgetExceededException):
            exhausted.verify(root, 'rk', max_attempts=1)

        fresh = Verifier(discharge_macaroons=candidates)
        fresh.satisfy_exact('ok = yes')
        # The other Verifier's spent budget has no effect here.
        assert fresh.verify(root, 'rk') is True
        assert fresh.verification_context.attempts == 2
