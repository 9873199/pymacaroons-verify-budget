import pytest
from pymacaroons import Macaroon,Verifier

def nested_bad_then_good():
    root=Macaroon(location='root',identifier='root',key='generated-root')
    root.add_third_party_caveat('service','generated-right','same-id')
    bad=Macaroon(location='service',identifier='same-id',key='generated-wrong')
    bad.add_third_party_caveat('nested','generated-nested','nested-id')
    good=Macaroon(location='service',identifier='same-id',key='generated-right')
    good.add_first_party_caveat('allowed')
    nested=Macaroon(location='nested',identifier='nested-id',key='generated-nested')
    return root,[root.prepare_for_request(x) for x in (bad,good,nested)]

def test_wrong_key_candidate_with_nested_caveat_does_not_abort_valid_sibling():
    root,candidates=nested_bad_then_good();callbacks=[]
    verifier=Verifier(discharge_macaroons=candidates)
    verifier.satisfy_general(lambda predicate:callbacks.append(predicate) or True)
    assert verifier.verify(root,'generated-root',max_depth=2,max_attempts=3)
    assert callbacks==['allowed']
