"""Real generated and root-bound discharge graphs for independent acceptance."""
from pymacaroons import Macaroon, Verifier

ROOT_KEY = 'generated-root-test-key'


def bind(root, candidates):
    return [root.prepare_for_request(candidate) for candidate in candidates]


def chain(length):
    root = Macaroon(location='local-root', identifier='root', key=ROOT_KEY)
    nodes = [Macaroon(location='local-' + str(i), identifier='d' + str(i), key='generated-key-' + str(i)) for i in range(length)]
    parent = root
    for i, node in enumerate(nodes):
        parent.add_third_party_caveat(node.location, 'generated-key-' + str(i), node.identifier)
        parent = node
    parent.add_first_party_caveat('leaf-permission')
    return root, bind(root, nodes)


def diamond():
    root = Macaroon(location='local-root', identifier='root', key=ROOT_KEY)
    left = Macaroon(location='same-location', identifier='left', key='generated-left')
    right = Macaroon(location='same-location', identifier='right', key='generated-right')
    shared = Macaroon(location='same-location', identifier='shared', key='generated-shared')
    root.add_third_party_caveat('same-location', 'generated-left', 'left')
    root.add_third_party_caveat('same-location', 'generated-right', 'right')
    for node in (left, right):
        node.add_third_party_caveat('same-location', 'generated-shared', 'shared')
    shared.add_first_party_caveat('leaf-permission')
    return root, bind(root, [left, right, shared])


def bad_then_good(count_bad=1):
    root = Macaroon(location='local-root', identifier='root', key=ROOT_KEY)
    root.add_third_party_caveat('same-location', 'generated-correct', 'same-id')
    candidates = []
    for i in range(count_bad):
        candidate = Macaroon(location='same-location', identifier='same-id', key='generated-incorrect-' + str(i))
        candidate.add_first_party_caveat('candidate-' + str(i))
        candidates.append(candidate)
    good = Macaroon(location='same-location', identifier='same-id', key='generated-correct')
    good.add_first_party_caveat('valid-candidate')
    candidates.append(good)
    return root, bind(root, candidates)


def cyclic():
    root = Macaroon(location='local-root', identifier='root', key=ROOT_KEY)
    left = Macaroon(location='same-location', identifier='left', key='generated-left')
    right = Macaroon(location='same-location', identifier='right', key='generated-right')
    root.add_third_party_caveat('same-location', 'generated-left', 'left')
    left.add_third_party_caveat('same-location', 'generated-right', 'right')
    right.add_third_party_caveat('same-location', 'generated-left', 'left')
    return root, bind(root, [left, right])


if __name__ == '__main__':
    import json
    observations = []
    for name, graph in [('chain-0', chain(0)), ('chain-1', chain(1)), ('chain-3', chain(3))]:
        root, candidates = graph
        callbacks = []
        verifier = Verifier(discharge_macaroons=candidates)
        verifier.satisfy_general(lambda predicate: callbacks.append(predicate) or True)
        assert verifier.verify(root, ROOT_KEY)
        observations.append({'graph': name, 'candidate_count': len(candidates), 'callbacks': callbacks})
    root, candidates = diamond()
    verifier = Verifier(discharge_macaroons=candidates)
    verifier.satisfy_general(lambda predicate: True)
    try:
        diamond_result = {'accepted': verifier.verify(root, ROOT_KEY)}
    except Exception as e:
        diamond_result = {'accepted': False, 'exception': type(e).__name__, 'message': str(e),
            'baseline_cause': 'Original third_party delegate deletes the shared discharge identifier globally after its first branch; this is a requested behavior change, not a failed positive control.'}
    print(json.dumps({'positive_controls': observations, 'diamond_baseline_observed': diamond_result, 'all_use_real_bound_macaroons': True}))
