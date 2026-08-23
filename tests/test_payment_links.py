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
mismatches = cc.paypal_amount_mismatches

# The three rates the shop charges for one track.
TABLE = "<td>&#8364;45</td><td>&#8364;160</td><td>&#8364;190</td>".replace(
    "&#8364;", "€"
)


def page(href: str) -> str:
    return f'<a class="paylink" href="{href}">Pay &#8364;160</a>'


class TestOnlyThePayPalShapeWithAnAmountInItShips:
    """paypal.me is allowed; every other PayPal shape is not.

    The distinction is not cosmetic. A PayPal.Me path carries the amount, so
    it can be read here. paypal.com/ncp/ and the old cgi-bin buttons put the
    amount back in an object only the account holder can see, which is the
    setup that hid a live EUR 1,200 charge behind a EUR 25 label.
    """

    def test_paypal_me_with_an_amount_is_allowed(self):
        assert not unverified(page("https://paypal.me/gabrielgga00/45EUR"))

    def test_the_newer_hosted_payment_link_is_not(self):
        assert unverified(page("https://www.paypal.com/ncp/payment/ABC123XYZ"))

    def test_paypalme_on_the_main_domain_is_not(self):
        assert unverified(page("https://www.paypal.com/paypalme/hologrampeople"))

    def test_paypal_checkout_is_not(self):
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
    def test_the_set_is_exactly_what_has_been_established(self):
        # A canary. Adding a host to this set is a claim about how its amounts
        # were established, so it requires deliberately editing this test and
        # recording that here.
        #
        # buy.stripe.com, 17 August 2026: the three links were created and read
        # back through GetPaymentLinks and GetPaymentLinksPaymentLinkLineItems.
        # EUR 45, 160 and 190, all tax_behavior "inclusive", automatic_tax off,
        # amount_tax 0.
        #
        # paypal.me, 22 August 2026: on a different basis. Nothing was read
        # through PayPal's API, which still returns 401 from here, and the page
        # itself is blocked by the egress proxy. It is allowed because a
        # PayPal.Me link states its amount in the URL path rather than in a
        # stored object, so paypal_amount_mismatches() below checks it against
        # the rate table directly. The handle rests on Gabriel's statement, and
        # that is a question of who receives, not of how much.
        assert cc.VERIFIED_PAYMENT_HOSTS == {"buy.stripe.com", "paypal.me"}

    def test_a_lookalike_host_does_not_inherit_the_allowlist(self):
        # The membership test was `entry in url`, substring matching against
        # the whole URL, which this file's own comment calls out as the
        # sloppiness the check exists to prevent. Short entries make it worse:
        # "paypal.me" sits inside "paypal.men". Found by trying it, not by
        # reading it.
        for host in (
            "https://paypal.me.attacker.example/steal",
            "https://notpaypal.men/steal",
            "https://buy.stripe.com.attacker.example/x",
            "https://paypal.me.evil.example./x",  # trailing dot is still a FQDN
        ):
            assert unverified(page(host)), host

    def test_the_allowlist_is_not_matched_against_the_query_string(self):
        assert unverified(page("https://evil.example/checkout?ref=paypal.me"))

    def test_the_real_hosts_still_pass_with_and_without_www(self):
        assert not unverified(page("https://paypal.me/gabrielgga00/45EUR"))
        assert not unverified(page("https://www.paypal.me/gabrielgga00/45EUR"))
        assert not unverified(page("https://PayPal.Me/gabrielgga00/45EUR"))
        assert not unverified(page("https://buy.stripe.com/dRm28q3Z06fM6s27JTabK02"))

    def test_the_bare_paypal_domain_is_still_not_allowed(self):
        # paypal.me is verified. paypal.com is not, and the difference is the
        # whole basis above, so a substring match that let paypal.com through
        # would erase it.
        assert "paypal.com" not in cc.VERIFIED_PAYMENT_HOSTS
        assert unverified(page("https://www.paypal.com/ncp/payment/ABC123XYZ"))

    def test_the_exceptions_cannot_charge_anyone(self):
        # Every entry is one exact URL, never a host prefix, because "the host
        # contains stripe" is the sloppiness the check exists to prevent.
        for url in cc.NON_PAYMENT_PROVIDER_LINKS:
            assert url.startswith("https://")
            assert not url.endswith("/")


class TestTheCheckIsNotTriviallyTrue:
    def test_it_finds_every_bad_link_on_a_page_not_just_the_first(self):
        body = page("https://www.paypal.com/ncp/payment/A") + page("https://ko-fi.com/b")
        assert len(unverified(body)) == 2

    def test_a_verified_and_an_unverified_link_together_still_fails(self):
        body = page("https://buy.stripe.com/dRm28q3Z06fM6s27JTabK02") + page(
            "https://www.paypal.com/ncp/payment/ABC123XYZ"
        )
        assert unverified(body) == ["https://www.paypal.com/ncp/payment/ABC123XYZ"]


class TestNoPaymentLinkEscapesThePriceCheck:
    """Two regexes decided whether a link got its price checked, and they
    disagreed.

    The anchor scan required a slash after the host. A link with no path, or
    with only a query string, was therefore accepted as verified by the href
    scan and then skipped by the price check, so a button reading "Pay EUR 99"
    on a page quoting nothing of the sort raised no failure at all. A loop over
    nothing emits nothing, and the run still printed all checks passed.

    Found by comparing the two scans against each other, not by reading them.
    """

    def _anchor(self, href: str) -> str:
        return f'<a href="{href}">Pay &#8364;99</a>'

    def test_a_link_with_no_path_is_price_checked(self):
        assert cc.verified_payment_anchors(self._anchor("https://buy.stripe.com"))

    def test_a_link_with_only_a_query_string_is_price_checked(self):
        assert cc.verified_payment_anchors(self._anchor("https://buy.stripe.com?s=abc"))

    def test_a_normal_link_is_still_price_checked(self):
        assert cc.verified_payment_anchors(self._anchor("https://buy.stripe.com/abc"))

    def test_a_lookalike_host_is_not_treated_as_a_payment_anchor(self):
        assert not cc.verified_payment_anchors(
            self._anchor("https://buy.stripe.com.evil.example/x")
        )

    def test_the_two_scans_agree_on_the_real_pages(self):
        for page_path in (ROOT / "docs").glob("*.html"):
            body = page_path.read_text(encoding="utf-8")
            assert cc.unchecked_payment_links(body) == [], page_path.name

    def test_a_link_the_anchor_scan_cannot_reach_is_reported(self):
        # An href with no closing anchor is seen by one scan and not the other.
        # Whatever it promises, nothing would check it.
        body = '<a href="https://buy.stripe.com/abc">Pay &#8364;99'
        assert cc.unchecked_payment_links(body) == ["https://buy.stripe.com/abc"]


class TestAPayPalLinkChargesWhatTheButtonSays:
    """The amount check, which is why paypal.me is allowed at all.

    Running it over the real shop only proves the shop is clean today. These
    hand it pages that do not exist, so it cannot quietly stop biting.
    """

    def test_the_three_links_on_the_shop_are_clean(self):
        shop = (ROOT / "docs" / "shop.html").read_text(encoding="utf-8")
        assert mismatches(shop, TABLE) == []

    def test_an_amount_the_table_does_not_quote_fails(self):
        # The shape of the original defect, at its original number.
        problems = mismatches(page("https://paypal.me/gabrielgga00/1200EUR"), TABLE)
        assert problems and "1200" in problems[0]

    def test_a_bare_handle_fails(self):
        # Opens a box the payer types into, under a button naming a price.
        assert mismatches(page("https://paypal.me/gabrielgga00"), TABLE)

    def test_a_trailing_slash_does_not_smuggle_a_bare_handle_through(self):
        assert mismatches(page("https://paypal.me/gabrielgga00/"), TABLE)

    def test_a_missing_currency_fails(self):
        # Without a currency the charge follows an account setting no reader
        # of the page can see.
        assert mismatches(page("https://paypal.me/gabrielgga00/45"), TABLE)

    def test_a_non_euro_currency_fails(self):
        assert mismatches(page("https://paypal.me/gabrielgga00/45USD"), TABLE)

    def test_the_www_variant_is_checked_too(self):
        assert mismatches(page("https://www.paypal.me/gabrielgga00/1200EUR"), TABLE)

    def test_it_reports_every_bad_link_not_just_the_first(self):
        body = page("https://paypal.me/x/1200EUR") + page("https://paypal.me/y/45USD")
        assert len(mismatches(body, TABLE)) == 2

    def test_a_good_link_beside_a_bad_one_still_fails(self):
        body = page("https://paypal.me/x/45EUR") + page("https://paypal.me/y/1200EUR")
        assert len(mismatches(body, TABLE)) == 1

    def test_an_empty_rate_table_fails_rather_than_passes(self):
        # A page whose table could not be read is not a page whose amounts
        # agree with it.
        assert mismatches(page("https://paypal.me/gabrielgga00/45EUR"), "")


class TestAPriceInAButtonMustMatchTheTable:
    """The check for this fired zero times across the whole site.

    Its pattern was `>\\s*(Pay[^<]{0,40})<`, anchored to a capital "Pay" at the
    start of the text. The shop's buttons read "Mastering, pay EUR 45", so the
    only things it matched were the two section labels, which name no amount.
    The inner loop never ran, and a check written for the EUR 25 / EUR 1,200
    wrong-checkout bug had never once executed while the suite reported "all
    129 consistency checks passed".

    Counted before fixing: 0 firings site-wide. After: 6.
    """

    TABLE_ROW = '<td class="n">€45</td>'

    def promise(self, text: str) -> str:
        return f'<a class="paylink" href="https://paypal.me/x/45EUR">{text}</a>'

    def test_the_shops_own_buttons_are_seen(self):
        shop = (ROOT / "docs" / "shop.html").read_text(encoding="utf-8")
        assert cc.promised_amounts(shop), "the scan must reach the real buttons"

    def test_it_sees_a_lowercase_pay_that_does_not_start_the_label(self):
        # The exact shape the old pattern missed.
        assert cc.promised_amounts(self.promise("Mastering, pay €45")) == ["45"]

    def test_it_still_sees_the_old_shape(self):
        assert cc.promised_amounts(self.promise("Pay €45")) == ["45"]

    def test_a_label_naming_no_amount_promises_nothing(self):
        assert cc.promised_amounts(self.promise("Pay by card, one track")) == []

    def test_a_price_with_no_payment_word_is_not_a_promise(self):
        # A rate table cell is not a promise; only the scan over the table
        # should see those, or every row would be compared against itself.
        assert cc.promised_amounts('<td class="n">€45</td>') == []

    def test_payment_as_a_substring_does_not_trigger_it(self):
        assert cc.promised_amounts(self.promise("Payment terms: €45")) == []

    def test_every_amount_in_one_label_is_returned(self):
        assert cc.promised_amounts(self.promise("pay €45 now, €160 later")) == ["45", "160"]

    def test_the_real_pages_promise_only_amounts_their_tables_quote(self):
        import re as _re

        for page_path in (ROOT / "docs").glob("*.html"):
            body = page_path.read_text(encoding="utf-8")
            table = "".join(_re.findall(r'<td class="n">(€[\d.,]+)</td>', body))
            for amount in cc.promised_amounts(body):
                assert f"€{amount}" in table, f"{page_path.name} promises €{amount}"
