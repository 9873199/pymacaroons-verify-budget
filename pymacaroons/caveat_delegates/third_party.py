from __future__ import unicode_literals
import binascii

from nacl.secret import SecretBox

from pymacaroons import Caveat
from pymacaroons.utils import (
    convert_to_bytes,
    truncate_or_pad,
    generate_derived_key,
    sign_third_party_caveat,
)
from pymacaroons.exceptions import (
    MacaroonBudgetExceededException,
    MacaroonDischargeCycleException,
    MacaroonUnmetCaveatException,
    MacaroonVerificationFailedException,
)
from .base_third_party import (
    BaseThirdPartyCaveatDelegate,
    BaseThirdPartyCaveatVerifierDelegate,
)


class ThirdPartyCaveatDelegate(BaseThirdPartyCaveatDelegate):

    def __init__(self, *args, **kwargs):
        super(ThirdPartyCaveatDelegate, self).__init__(*args, **kwargs)

    def add_third_party_caveat(self,
                               macaroon,
                               location,
                               key,
                               key_id,
                               **kwargs):
        derived_key = truncate_or_pad(
            generate_derived_key(convert_to_bytes(key))
        )
        old_key = truncate_or_pad(binascii.unhexlify(macaroon.signature_bytes))
        box = SecretBox(key=old_key)
        verification_key_id = box.encrypt(
            derived_key, nonce=kwargs.get('nonce')
        )
        caveat = Caveat(
            caveat_id=key_id,
            location=location,
            verification_key_id=verification_key_id,
            version=macaroon.version
        )
        macaroon.caveats.append(caveat)
        encode_key = binascii.unhexlify(macaroon.signature_bytes)
        macaroon.signature = sign_third_party_caveat(
            encode_key,
            caveat._verification_key_id,
            caveat._caveat_id
        )
        return macaroon


class ThirdPartyCaveatVerifierDelegate(BaseThirdPartyCaveatVerifierDelegate):

    def __init__(self, discharge_macaroons=None, *args, **kwargs):
        super(ThirdPartyCaveatVerifierDelegate, self).__init__(*args, **kwargs)
        # Keep every supplied discharge macaroon, including several candidates
        # that share an identifier. A dict would silently drop all but one of
        # them, so the verifier could never reach a valid candidate listed
        # behind an invalid one.
        self.discharge_macaroons = {}
        for macaroon in discharge_macaroons or []:
            self.discharge_macaroons.setdefault(
                macaroon.identifier_bytes, []
            ).append(macaroon)

    def verify_third_party_caveat(self,
                                  verifier,
                                  caveat,
                                  root,
                                  macaroon,
                                  signature):
        context = verifier.verification_context
        candidates = self.discharge_macaroons.get(
            caveat.caveat_id_bytes, []
        )
        if not candidates:
            raise MacaroonUnmetCaveatException(
                'Caveat not met. No discharge macaroon found for identifier: '
                '{}'.format(caveat.caveat_id_bytes)
            )

        caveat_key = self._extract_caveat_key(signature, caveat)

        # Every candidate that is actually entered counts as an attempt, even
        # if a later backtrack discards the branch. The budget is shared by
        # the whole verification, so failed branches never get their attempts
        # refunded.
        last_failure = None
        for candidate in candidates:
            try:
                # Numeric budget exhaustion and the path cycle guard are raised
                # here, before any verification work (so no business caveat
                # callbacks run). A budget breach is terminal; a cycle only
                # invalidates this branch and lets the next candidate run.
                context.enter_discharge(candidate)
            except MacaroonDischargeCycleException as exc:
                # The re-entrant entry never started, so nothing was charged
                # and there is no path slot to release.
                last_failure = exc
                continue

            try:
                caveat_met = verifier.verify_discharge(
                    root,
                    candidate,
                    caveat_key,
                )
            except MacaroonBudgetExceededException:
                # A nested discharge hit the budget: stop immediately instead
                # of trying another candidate and spending more callbacks.
                raise
            except MacaroonVerificationFailedException as exc:
                # Bad signature, unmet caveat, nested cycle, etc. The attempt
                # remains spent; move on to the next candidate without
                # refunding it.
                context.exit_discharge(candidate)
                last_failure = exc
                continue

            context.exit_discharge(candidate)
            if caveat_met:
                return True

        if last_failure is not None:
            # Every candidate failed: surface the concrete reason (e.g. the
            # cycle) rather than a generic signature mismatch.
            raise last_failure
        return False

    def update_signature(self, signature, caveat):
        return binascii.unhexlify(
            sign_third_party_caveat(
                signature,
                caveat._verification_key_id,
                caveat._caveat_id
            )
        )

    def _extract_caveat_key(self, signature, caveat):
        key = truncate_or_pad(signature)
        box = SecretBox(key=key)
        decrypted = box.decrypt(caveat._verification_key_id)
        return decrypted
