"""Real discharge graphs and per-root budget boundaries; no fabricated tokens."""
import importlib.util
from pathlib import Path
import sys

import pytest
from pymacaroons import Verifier
from pymacaroons.exceptions import MacaroonInvalidSignatureException

from macaroon_api import verify, BudgetError, CycleError

spec = importlib.util.spec_from_file_location('macaroon_real_graphs', Path(__file__).with_name('macaroon-fixtures.py'))
graphs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = graphs
spec.loader.exec_module(graphs)


def observed(candidates):
    calls = []
    verifier = Verifier(discharge_macaroons=candidates)
    verifier.satisfy_general(lambda predicate: calls.append(predicate) or True)
    return verifier, calls


@pytest.mark.parametrize('length', [0, 1, 3])
def test_exact_depth_and_attempt_limit_accepts_valid_chain(length):
    root, candidates = graphs.chain(length)
    verifier, callbacks = observed(candidates)
    assert verify(verifier, root, graphs.ROOT_KEY, depth=length, attempts=length)
    assert callbacks == ['leaf-permission']


@pytest.mark.parametrize('dimension', ['depth', 'attempts'])
def test_next_discharge_is_rejected_before_leaf_callback(dimension):
    root, candidates = graphs.chain(3)
    verifier, callbacks = observed(candidates)
    bounds = {'depth': 3, 'attempts': 3}
    bounds[dimension] = 2
    with pytest.raises(BudgetError):
        verify(verifier, root, graphs.ROOT_KEY, **bounds)
    assert not callbacks


def test_bad_candidate_does_not_hide_later_valid_one():
    root, candidates = graphs.bad_then_good(3)
    verifier, callbacks = observed(candidates)
    assert verify(verifier, root, graphs.ROOT_KEY, depth=1, attempts=4)
    assert callbacks[-1] == 'valid-candidate'


def test_failed_branch_attempts_cannot_be_refunded():
    root, candidates = graphs.bad_then_good(4)
    verifier, callbacks = observed(candidates)
    with pytest.raises(BudgetError):
        verify(verifier, root, graphs.ROOT_KEY, depth=1, attempts=3)
    assert 'valid-candidate' not in callbacks and len(callbacks) <= 3


def test_diamond_reuse_is_not_a_cycle_and_checks_each_branch():
    root, candidates = graphs.diamond()
    verifier, callbacks = observed(candidates)
    assert verify(verifier, root, graphs.ROOT_KEY, depth=2, attempts=4)
    assert callbacks == ['leaf-permission', 'leaf-permission']


def test_diamond_attempt_budget_is_shared_between_branches():
    root, candidates = graphs.diamond()
    verifier, callbacks = observed(candidates)
    with pytest.raises(BudgetError):
        verify(verifier, root, graphs.ROOT_KEY, depth=2, attempts=3)
    assert callbacks == ['leaf-permission']


def test_real_cycle_is_bounded_without_python_recursion_error():
    root, candidates = graphs.cyclic()
    verifier, callbacks = observed(candidates)
    with pytest.raises((BudgetError, CycleError, MacaroonInvalidSignatureException)):
        verify(verifier, root, graphs.ROOT_KEY, depth=8, attempts=8)
    assert not callbacks


def test_root_binding_is_not_skipped_for_reused_discharge():
    from pymacaroons import Macaroon
    root, candidates = graphs.chain(1)
    other_root = Macaroon(location='different-root', identifier='different-root', key=graphs.ROOT_KEY)
    other_root.add_third_party_caveat('local-0', 'generated-key-0', 'd0')
    verifier, callbacks = observed(candidates)
    with pytest.raises(MacaroonInvalidSignatureException):
        verify(verifier, other_root, graphs.ROOT_KEY, depth=1, attempts=1)


def test_failed_call_does_not_mutate_candidates_or_next_budget():
    root, candidates = graphs.chain(3)
    before = [candidate.serialize() for candidate in candidates]
    verifier, callbacks = observed(candidates)
    with pytest.raises(BudgetError):
        verify(verifier, root, graphs.ROOT_KEY, depth=3, attempts=2)
    assert not callbacks
    assert verify(verifier, root, graphs.ROOT_KEY, depth=3, attempts=3)
    assert verify(verifier, root, graphs.ROOT_KEY, depth=3, attempts=3)
    assert callbacks == ['leaf-permission', 'leaf-permission']
    assert [candidate.serialize() for candidate in candidates] == before


def test_legacy_signature_without_limits_keeps_working():
    root, candidates = graphs.chain(2)
    verifier, callbacks = observed(candidates)
    assert verifier.verify(root, graphs.ROOT_KEY)
    assert callbacks == ['leaf-permission']
