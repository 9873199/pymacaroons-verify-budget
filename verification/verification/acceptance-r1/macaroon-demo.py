import importlib.util,sys
from pathlib import Path
from pymacaroons import Verifier
import pymacaroons.verifier as vm
from test_macaroon_nested_candidate import nested_bad_then_good
from test_macaroon_context import same_identifier_graph
s=importlib.util.spec_from_file_location('demo_graphs',Path(__file__).with_name('macaroon-fixtures.py'));graphs=importlib.util.module_from_spec(s);s.loader.exec_module(graphs)

def show(label,root,candidates,key,depth,attempts):
    callbacks=[];count=[0];original=vm.hmac_digest
    def counted(*args):count[0]+=1;return original(*args)
    verifier=Verifier(discharge_macaroons=candidates)
    verifier.satisfy_general(lambda predicate:callbacks.append(predicate) or True)
    vm.hmac_digest=counted
    try:
        result=verifier.verify(root,key,max_depth=depth,max_attempts=attempts)
        print(label+': accepted='+str(result))
    except Exception as error:
        print(label+': '+type(error).__name__+': '+str(error))
    finally:vm.hmac_digest=original
    print('  candidate attempts:',verifier.verification_context.attempts,'signature entries:',count[0],'callbacks:',callbacks)

for length,budget in [(3,3),(3,2)]:
    root,candidates=graphs.chain(length);show('Chain length 3, attempts '+str(budget),root,candidates,graphs.ROOT_KEY,3,budget)
root,candidates=graphs.diamond();show('Shared discharge on two branches',root,candidates,graphs.ROOT_KEY,2,4)
root,candidates=nested_bad_then_good();show('Wrong-key candidate before a valid sibling',root,candidates,'generated-root',2,3)
root,candidates=same_identifier_graph(True);show('Same identifier under a new derived key, budget 2',root,candidates,'generated-independent-root',2,2)
