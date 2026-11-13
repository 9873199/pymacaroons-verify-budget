"""Candidate identity includes derived verification context, not identifier alone."""
from pymacaroons import Macaroon, Verifier
import pytest
from macaroon_api import verify, BudgetError

ROOT_KEY = 'generated-independent-root'


def same_identifier_graph(nested):
    root = Macaroon(location='generated-root', identifier='root', key=ROOT_KEY)
    first = Macaroon(location='shared-location', identifier='same-id',
                     key='generated-context-first')
    second = Macaroon(location='shared-location', identifier='same-id',
                      key='generated-context-second')
    root.add_third_party_caveat('shared-location', 'generated-context-first', 'same-id')
    if nested:
        first.add_third_party_caveat('shared-location', 'generated-context-second', 'same-id')
    else:
        root.add_third_party_caveat('shared-location', 'generated-context-second', 'same-id')
        first.add_first_party_caveat('first-authorized')
    second.add_first_party_caveat('second-authorized')
    return root, [root.prepare_for_request(first), root.prepare_for_request(second)]


@pytest.mark.parametrize('nested', [False, True])
def test_same_identifier_candidates_in_distinct_contexts_are_legal(nested):
    root, candidates = same_identifier_graph(nested)
    verifier = Verifier(discharge_macaroons=candidates)
    callbacks = []
    verifier.satisfy_general(lambda predicate: callbacks.append(predicate) or True)
    assert verify(verifier, root, ROOT_KEY, depth=2 if nested else 1, attempts=3)
    assert 'second-authorized' in callbacks
    if not nested:
        assert 'first-authorized' in callbacks


@pytest.mark.parametrize('nested', [False, True])
def test_failed_candidate_attempt_still_consumes_shared_budget(nested):
    root, candidates = same_identifier_graph(nested)
    verifier = Verifier(discharge_macaroons=candidates)
    callbacks = []
    verifier.satisfy_general(lambda predicate: callbacks.append(predicate) or True)
    with pytest.raises(BudgetError):
        verify(verifier, root, ROOT_KEY, depth=2 if nested else 1, attempts=2)
    assert 'second-authorized' not in callbacks
