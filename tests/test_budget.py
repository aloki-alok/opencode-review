from helpers import src  # noqa: F401  (puts src/ on the path)

# isort: split

import unittest

from budget import Budget, find_budget, parse_budget


class BudgetTest(unittest.TestCase):
    def test_small_change_gets_small_budget(self):
        self.assertEqual(find_budget(2, turn_p90=14), Budget(turns=6, seconds=90))

    def test_tiers(self):
        self.assertEqual(find_budget(20, 14).seconds, 90)
        # Measured: a 196-line PR's turns ran about 25 s each and hit a 180 s cap (docs #154).
        self.assertEqual(find_budget(21, 14).seconds, 240)
        self.assertEqual(find_budget(301, 14).seconds, 240)
        self.assertEqual(find_budget(50_000, 14).seconds, 240)

    def test_turns_fit_the_time_at_p90(self):
        for lines in (0, 2, 100, 1000):
            for p90 in (5, 14, 30):
                b = find_budget(lines, p90)
                self.assertLessEqual(b.turns * p90, b.seconds, (lines, p90))
                self.assertGreaterEqual(b.turns, 3)

    def test_slower_model_gets_fewer_turns(self):
        self.assertLess(find_budget(100, 30).turns, find_budget(100, 10).turns)

    def test_parse(self):
        self.assertIsNone(parse_budget('auto'))
        self.assertEqual(parse_budget('12:200'), Budget(12, 200))
        for bad in ('12', 'a:b', '0:100', '5:0', ''):
            with self.assertRaises(ValueError, msg=bad):
                parse_budget(bad)


if __name__ == '__main__':
    unittest.main()
