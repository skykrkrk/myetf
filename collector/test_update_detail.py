import unittest

from update_detail import build_distribution_events, convert_ticker_to_isin


class SeibroDetailTests(unittest.TestCase):
    def test_convert_alpha_numeric_ticker_to_isin(self):
        self.assertEqual(convert_ticker_to_isin("0094M0"), "KR70094M0005")

    def test_tax_base_is_capped_by_per_unit_distribution(self):
        records = [
            {
                "ANYTM_REPTG_DT": "20261116",
                "TAXSTD": "1000",
            },
            {
                "ANYTM_REPTG_DT": "20261117",
                "TAXSTD": "990",
                "TOT_DIV_PAY_AMT": "100000000",
                "NAV_AMT": "9900",
                "FUND_NETASST_TOTAMT": "1000",
            },
        ]

        event = build_distribution_events(records)[0]

        self.assertEqual(event["amount"], 9.9)
        self.assertEqual(event["tax_base"], 9.9)
        self.assertEqual(event["tax_rate"], 0.99)

    def test_tax_base_uses_previous_tax_standard_price(self):
        records = [
            {
                "ANYTM_REPTG_DT": "20261116",
                "TAXSTD": "1000",
            },
            {
                "ANYTM_REPTG_DT": "20261117",
                "TAXSTD": "990",
                "TOT_DIV_PAY_AMT": "1000000000",
                "NAV_AMT": "9900",
                "FUND_NETASST_TOTAMT": "1000",
            },
        ]

        event = build_distribution_events(records)[0]

        self.assertEqual(event["amount"], 99.0)
        self.assertEqual(event["tax_base"], 10.0)
        self.assertEqual(event["tax_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
