import unittest

from update_detail import build_distribution_events, convert_ticker_to_isin


class SeibroDetailTests(unittest.TestCase):
    def test_convert_alpha_numeric_ticker_to_isin(self):
        self.assertEqual(convert_ticker_to_isin("0094M0"), "KR70094M0005")

    def setUp(self):
        self.price_records = [
            {
                "ANYTM_REPTG_DT": "20261111",
                "TAXSTD": "9917.63",
                "NAV_AMT": "13133.88",
            },
            {
                "ANYTM_REPTG_DT": "20261112",
                "TAXSTD": "9913.05",
                "NAV_AMT": "12905.27",
            },
            {
                "ANYTM_REPTG_DT": "20261113",
                "TAXSTD": "9913.48",
                "NAV_AMT": "12815.17",
            },
        ]

    def payment_record(self, amount, settlement_tax_standard):
        return {
            "RGT_STD_DT": "20261113",
            "ESTM_STDPRC": str(amount),
            "TAXSTD": str(settlement_tax_standard),
        }

    def test_uses_ex_date_tax_standard_and_payment_status_tax_standard(self):
        event = build_distribution_events(
            self.price_records,
            [self.payment_record(420, 9928.05)]
        )[0]

        self.assertEqual(event["ex_date"], "2026-11-12")
        self.assertEqual(event["distribution_record_date"], "2026-11-13")
        self.assertEqual(event["amount"], 420.0)
        self.assertEqual(event["ex_date_tax_standard_price"], 9913.05)
        self.assertEqual(event["settlement_tax_standard_price"], 9928.05)
        self.assertEqual(event["tax_base"], 15.0)

    def test_caps_tax_base_at_distribution_amount(self):
        event = build_distribution_events(
            self.price_records,
            [self.payment_record(10, 10000)]
        )[0]

        self.assertEqual(event["tax_base"], 10.0)

    def test_floors_negative_difference_to_zero(self):
        event = build_distribution_events(
            self.price_records,
            [self.payment_record(420, 9900)]
        )[0]

        self.assertEqual(event["tax_base"], 0)


if __name__ == "__main__":
    unittest.main()
