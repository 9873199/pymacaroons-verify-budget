from pymacaroons.exceptions import MacaroonBudgetExceededException,MacaroonDischargeCycleException
BudgetError=MacaroonBudgetExceededException
CycleError=MacaroonDischargeCycleException
def verify(verifier,root,key,depth=None,attempts=None):
    return verifier.verify(root,key,max_depth=depth,max_attempts=attempts)
