"""A payment link nobody has read must not be able to reach a page.

The shop once carried a link that read as a EUR 25 deposit and was a live
EUR 1,200 charge for a different service, with VAT added on top of a page that
says no VAT is added. It survived two rounds of review because it looked right.
The rule since then is that a host goes on VERIFIED_PAYMENT_HOSTS only when
someone has read the amount and tax treatment through the provider's own API.

The consistency check enforces that, but running it over the real pages only
proves those pages are clean today. These pin the check itself, against pages
that do not exist, so it cannot quietly stop biting.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "consistency_check", ROOT / "tools" / "consistency_check.py"
)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

unverified = cc.unverified_payment_links


def page(href: str) -> str:
    return f'<a class="paylink" href="{href}">Pay &#8364;160</a>'


class TestPayPalCannotShipUnread:
    # PayPal is the live case: Gabriel has a business account and has asked for
    # a button more than once, and the account has never been readable from
    # here. Both URL shapes it would take are covered.
    def test_paypal_me(self):
        assert unverified(page("https://paypal.me/hologrampeople/160"))

    def test_paypalme_on_the_main_domain(self):
        assert unverified(page("https://www.paypal.com/paypalme/hologrampeople"))

    def test_paypal_checkout(self):
        assert unverified(page("https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick"))


class TestOtherProviders:
    def test_gumroad(self):
        assert unverified(page("https://gumroad.com/l/duress"))

    def test_ko_fi(self):
        assert unverified(page("https://ko-fi.com/hologrampeople"))

    def test_lemonsqueezy(self):
        assert unverified(page("https://hologram.lemonsqueezy.com/checkout"))

    def test_buymeacoffee(self):
        assert unverified(page("https://buymeacoffee.com/hologrampeople"))


class TestWhatIsAllowed:
    def test_the_read_stripe_links_pass(self):
        assert not unverified(page("https://buy.stripe.com/dRm28q3Z06fM6s27JTabK02"))

    def test_a_cited_privacy_page_is_not_a_payment_link(self):
        # The data protection notice has to cite it, and it cannot charge anyone.
        assert not unverified(page("https://stripe.com/privacy"))

    def test_an_unrelated_link_is_left_alone(self):
        assert not unverified(page("https://notgabriels-sys.github.io/albumdesign/"))

    def test_a_mailto_is_not_a_payment_link(self):
        assert not unverified('<a href="mailto:hologrampeoplemusic@gmail.com">mail</a>')


class TestTheAllowlistItself:
    def test_only_stripe_has_been_read(self):
        # A canary. Adding a host to this set is a claim that someone read the
        # provider's objects, so it should require deliberately editing this
        # test and saying, here, what was read and when. If PayPal ever joins
        # the set, this line is where the evidence gets recorded.
        assert cc.VERIFIED_PAYMENT_HOSTS == {"buy.stripe.com"}

    def test_paypal_is_not_quietly_allowed(self):
        assert not any("paypal" in h.lower() for h in cc.VERIFIED_PAYMENT_HOSTS)

    def test_the_exceptions_cannot_charge_anyone(self):
        # Every entry is one exact URL, never a host prefix, because "the host
        # contains stripe" is the sloppiness the check exists to prevent.
        for url in cc.NON_PAYMENT_PROVIDER_LINKS:
            assert url.startswith("https://")
            assert not url.endswith("/")


class TestTheCheckIsNotTriviallyTrue:
    def test_it_finds_every_bad_link_on_a_page_not_just_the_first(self):
        body = page("https://paypal.me/a") + page("https://ko-fi.com/b")
        assert len(unverified(body)) == 2

    def test_a_verified_and_an_unverified_link_together_still_fails(self):
        body = page("https://buy.stripe.com/dRm28q3Z06fM6s27JTabK02") + page(
            "https://paypal.me/hologrampeople"
        )
        assert unverified(body) == ["https://paypal.me/hologrampeople"]
